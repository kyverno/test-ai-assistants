#!/usr/bin/env python3
"""dependabot-policy-engine.py — deterministic APPROVE/FLAG for a Dependabot PR.

Hermes webhook `script` hook contract (see config.yaml's dependabot-pr
route): reads the route payload as JSON from stdin, either prints
"[SILENT]" (Hermes drops the event) or prints a JSON object to stdout that
replaces the payload used for prompt templating.

No LLM call happens anywhere in this file. Every check below is final —
the dependabot-bot profile that reads `kyctrl_verdict` only explains it,
per profiles/dependabot-bot/SOUL.md.

Checks performed, in order, any of which can FLAG independent of the rest:
  1. sender is dependabot[bot]                      -> else [SILENT], not FLAG
  2. ecosystem is in the auto-merge allowlist        -> else FLAG
  3. update-type isn't in the always-flag list       -> else FLAG (e.g. semver-major)
  4. CI is green on the PR head SHA (if required)    -> else FLAG
  5. Socket.dev score clears the threshold           -> else FLAG (fail closed)
  6. Copilot's review has no flagged keywords         -> else FLAG (downgrade-only)
Only if all of the above pass: APPROVE.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / "settings.yaml"
GITHUB_API = "https://api.github.com"
SOCKET_API = "https://api.socket.dev/v0/purl"


# --------------------------------------------------------------------------
# settings.yaml loading — prefers PyYAML if present, falls back to a small
# parser scoped to this file's actual shape (2-space-indent maps, "- item"
# lists of scalars, no anchors/multiline strings) so this script has no
# hard dependency on a package that may not be installed in the Hermes
# container's Python.
# --------------------------------------------------------------------------
def load_settings() -> dict[str, Any]:
    text = SETTINGS_PATH.read_text()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        return _tiny_yaml_parse(text)


def _tiny_yaml_parse(text: str) -> dict[str, Any]:
    """Recursive-descent parser for this file's specific shape: nested
    2-space-indent maps, and "- scalar" lists of strings/numbers/bools
    directly under a key. No anchors, flow style, or multiline scalars.
    """
    lines = [
        line.split(" #", 1)[0].rstrip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    def parse_block(i: int, indent: int) -> tuple[Any, int]:
        first_stripped = lines[i].strip()
        is_list = first_stripped.startswith("- ")
        node: Any = [] if is_list else {}
        while i < len(lines):
            line = lines[i]
            cur_indent = len(line) - len(line.lstrip(" "))
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise ValueError(f"unexpected indent at: {line!r}")
            stripped = line.strip()
            if is_list:
                if not stripped.startswith("- "):
                    break
                node.append(_scalar(stripped[2:].strip()))
                i += 1
            else:
                key, _, value = stripped.partition(":")
                key, value = key.strip(), value.strip()
                if value == "":
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        next_indent = len(next_line) - len(next_line.lstrip(" "))
                    else:
                        next_indent = -1
                    if next_indent > indent:
                        child, i = parse_block(i + 1, next_indent)
                        node[key] = child
                    else:
                        node[key] = None
                        i += 1
                else:
                    node[key] = _scalar(value)
                    i += 1
        return node, i

    root, _ = parse_block(0, 0)
    return root


def _scalar(value: str) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


# --------------------------------------------------------------------------
# GitHub REST API — direct HTTP, no dependency on the `gh` binary being
# present in the Hermes container. Uses KYCTRL_READONLY_GITHUB_TOKEN, the
# comment-capable-but-non-merge token (see .env.example) — never the
# Actions-only GITHUB_TOKEN.
# --------------------------------------------------------------------------
def github_api(path: str, token: str) -> Any:
    req = urllib.request.Request(
        f"{GITHUB_API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


DEP_TRAILER_RE = re.compile(
    r"^-\s*dependency-name:\s*(?P<name>\S+)\s*$"
    r"(?:\n\s+dependency-version:\s*(?P<version>\S+)\s*$)?"
    r"(?:\n\s+dependency-type:\s*(?P<dtype>\S+)\s*$)?"
    r"(?:\n\s+update-type:\s*(?P<utype>\S+)\s*$)?",
    re.MULTILINE,
)


def parse_dependency_metadata(commit_messages: list[str]) -> list[dict[str, str]]:
    """Extract Dependabot's `updated-dependencies:` trailer block.

    Deliberately does NOT look at the PR title — see
    skills/dependabot-merge-policy.md for the documented title-parsing bug
    this sidesteps.
    """
    deps: list[dict[str, str]] = []
    for msg in commit_messages:
        for m in DEP_TRAILER_RE.finditer(msg):
            deps.append(
                {
                    "name": m.group("name"),
                    "version": m.group("version") or "",
                    "dependency_type": m.group("dtype") or "",
                    "update_type": m.group("utype") or "",
                }
            )
    return deps


def ecosystem_from_branch(head_ref: str) -> str:
    # Dependabot branch names are "dependabot/<package-manager>/<rest>".
    parts = head_ref.split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "dependabot" else "unknown"


def ci_passed(repo: str, sha: str, token: str) -> tuple[bool, str]:
    try:
        status = github_api(f"/repos/{repo}/commits/{sha}/status", token)
        state = status.get("state", "unknown")
        if state == "success":
            return True, "combined status: success"
        if state == "pending":
            return False, "combined status: pending (not green yet)"
        return False, f"combined status: {state}"
    except urllib.error.URLError as e:
        return False, f"could not reach CI status API ({e}) — failing closed"


def get_socket_score(ecosystem: str, package_name: str, api_key: str) -> tuple[float | None, str]:
    """Returns (score 0-100 or None, human-readable note). None = fail closed.

    NOTE: verify this request/response shape against
    https://docs.socket.dev/reference/introduction-to-socket-api before the
    first real run — Socket's batch `/purl` endpoint and the depscore/
    supplyChainRisk field names were confirmed via docs search, but the
    exact PURL ecosystem-name mapping (npm/pypi/golang/maven/etc. vs our
    Dependabot ecosystem strings like "npm_and_yarn", "gomod") needs a
    real-key smoke test — see docs/deployment.md Phase 0 checklist.
    """
    ecosystem_map = {
        "npm_and_yarn": "npm",
        "gomod": "golang",
        "docker": "docker",
        "github_actions": "githubactions",
    }
    purl_type = ecosystem_map.get(ecosystem)
    if purl_type is None:
        return None, f"no Socket.dev ecosystem mapping for '{ecosystem}' — failing closed"
    purl = f"pkg:{purl_type}/{package_name}"
    body = json.dumps({"components": [{"purl": purl}]}).encode()
    req = urllib.request.Request(
        SOCKET_API,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {_b64(api_key + ':')}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return None, f"Socket.dev API unreachable/unparseable ({e}) — failing closed"
    if not results:
        return None, f"'{package_name}' not found in Socket.dev's index — failing closed"
    entry = results[0]
    supply_chain_risk = entry.get("score", {}).get("supplyChainRisk")
    if supply_chain_risk is None:
        return None, f"Socket.dev returned no supplyChainRisk score for '{package_name}' — failing closed"
    score_0_100 = round(supply_chain_risk * 100)
    return score_0_100, f"'{package_name}' Socket.dev supply-chain score: {score_0_100}/100"


def _b64(s: str) -> str:
    import base64

    return base64.b64encode(s.encode()).decode()


def copilot_flags(repo: str, pr_number: int, token: str, settings: dict) -> tuple[bool, str]:
    copilot_logins = set(settings["global"]["copilot_review_bot_logins"])
    keywords = [k.lower() for k in settings["dependabot_bot"]["copilot_flag_keywords"]]
    texts: list[str] = []
    try:
        for review in github_api(f"/repos/{repo}/pulls/{pr_number}/reviews", token):
            if review.get("user", {}).get("login") in copilot_logins and review.get("body"):
                texts.append(review["body"])
        for comment in github_api(f"/repos/{repo}/pulls/{pr_number}/comments", token):
            if comment.get("user", {}).get("login") in copilot_logins and comment.get("body"):
                texts.append(comment["body"])
    except urllib.error.URLError as e:
        return False, f"could not reach Copilot review data ({e}) — not gating on it"
    if not texts:
        return False, "no Copilot review found yet — not gating on it"
    combined = " ".join(texts).lower()
    hit = next((k for k in keywords if k in combined), None)
    if hit:
        return True, f"Copilot's review contains flagged keyword '{hit}'"
    return False, "Copilot's review raised no flagged concerns"


def decide(payload: dict, settings: dict, token: str, socket_key: str) -> dict:
    pr = payload["pull_request"]
    repo = payload["repository"]["full_name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]
    head_ref = pr["head"]["ref"]

    ds = settings["dependabot_bot"]
    reasons: list[str] = []

    ecosystem = ecosystem_from_branch(head_ref)
    if ecosystem not in ds["auto_merge_ecosystems"]:
        reasons.append(f"ecosystem '{ecosystem}' is not in the auto-merge allowlist")
        return verdict("FLAG", reasons)

    commits = github_api(f"/repos/{repo}/pulls/{pr_number}/commits", token)
    deps = parse_dependency_metadata([c["commit"]["message"] for c in commits])
    if not deps:
        reasons.append("could not parse Dependabot's dependency metadata from the commit messages — failing closed")
        return verdict("FLAG", reasons)

    for dep in deps:
        if dep["update_type"] in ds["always_flag_update_types"]:
            reasons.append(f"'{dep['name']}' update-type '{dep['update_type']}' is always flagged")
    if any(r for r in reasons):
        return verdict("FLAG", reasons)

    if ds["require_ci_pass"]:
        ok, note = ci_passed(repo, head_sha, token)
        reasons.append(note)
        if not ok:
            return verdict("FLAG", reasons)

    if socket_key:
        for dep in deps:
            score, note = get_socket_score(ecosystem, dep["name"], socket_key)
            reasons.append(note)
            if score is None or score < ds["socket_score_threshold"]:
                return verdict("FLAG", reasons)
    else:
        # Deliberately NOT fail-closed like every other missing-signal case
        # above: an unconfigured SOCKET_DEV_API_KEY is an intentional "not
        # set up yet" state (see .env.example), not an error worth blocking
        # every merge on while Phase 0 is being tested end to end. Once a
        # key is added this branch stops being reachable.
        reasons.append("SOCKET_DEV_API_KEY not configured — supply-chain check skipped, not gating on it")

    flagged, note = copilot_flags(repo, pr_number, token, settings)
    reasons.append(note)
    if flagged:
        return verdict("FLAG", reasons)

    reasons.append("all checks passed: allowed ecosystem, no flagged update-type, CI green, "
                    "Socket.dev score above threshold, no Copilot concerns")
    return verdict("APPROVE", reasons)


def verdict(decision: str, reasons: list[str]) -> dict:
    return {
        "decision": decision,
        "reasons": reasons,
        "reasons_text": "\n".join(f"- {r}" for r in reasons),
    }


def main() -> None:
    payload_envelope = json.load(sys.stdin)
    payload = payload_envelope.get("payload", payload_envelope)

    pr = payload.get("pull_request")
    if not pr or pr.get("user", {}).get("login") != "dependabot[bot]":
        print("[SILENT]")
        return

    settings = load_settings()
    if not settings.get("dependabot_bot", {}).get("enabled", False):
        print("[SILENT]")
        return

    token = os.environ["KYCTRL_READONLY_GITHUB_TOKEN"]
    socket_key = os.environ.get("SOCKET_DEV_API_KEY", "")

    result = decide(payload, settings, token, socket_key)
    print(json.dumps({**payload_envelope, "kyctrl_verdict": result}))


if __name__ == "__main__":
    main()
