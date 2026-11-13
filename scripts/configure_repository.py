#!/usr/bin/env python3
"""Preview or apply repository rulesets using an authenticated GitHub CLI."""

import argparse
import base64
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
API_VERSION = "2026-03-10"
POLICY_FILES = [
    "protected-branches.json",
    "main-merge-owner.json",
    "sensitive-file-reviews.json",
]
SENSITIVE_PATHS = ["/.github/", "/policies/", "/scripts/", "/tests/"]


def render_codeowners(owner):
    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise ConfigurationError("The code owner must be a GitHub username.")
    lines = [
        "# Managed by scripts/configure_repository.py --prepare-codeowners.",
        "# Protect CI, CODEOWNERS itself, policies, tooling and their tests.",
    ]
    return "\n".join(lines + [f"{path} @{owner}" for path in SENSITIVE_PATHS]) + "\n"


def verify_codeowners(api, repo, sha, owner, branch):
    document = api.api(f"repos/{repo}/contents/.github/CODEOWNERS?ref={sha}")
    if document.get("type") != "file" or document.get("encoding") != "base64":
        raise ConfigurationError(f"{branch}: CODEOWNERS must be a regular text file.")
    content = base64.b64decode(document["content"]).decode("utf-8")
    if content.splitlines() != render_codeowners(owner).splitlines():
        raise ConfigurationError(
            f"{branch}: CODEOWNERS does not match @{owner}. Run --prepare-codeowners "
            "with the intended --merger, commit the result to both branches, and rerun CI."
        )


class ConfigurationError(Exception):
    pass


class ChecksNotReady(ConfigurationError):
    pass


class GitHub:
    def api(self, endpoint, method="GET", payload=None):
        command = [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: " + API_VERSION,
            endpoint,
        ]
        if payload is not None:
            command += ["--input", "-"]
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ConfigurationError(f"{method} {endpoint}: {detail}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def pages(self, endpoint, key=None):
        results = []
        separator = "&" if "?" in endpoint else "?"
        page = 1
        while True:
            value = self.api(f"{endpoint}{separator}per_page=100&page={page}")
            items = value[key] if key else value
            results.extend(items)
            if len(items) < 100:
                return results
            page += 1


def build_payloads(checks, merger_id, release_app_id=None):
    """Resolve repository-specific actors and optional release rules."""
    if not checks or merger_id <= 0:
        raise ConfigurationError(
            "At least one successful check and a valid merger ID are required."
        )
    payloads = [
        json.loads((ROOT / "policies" / name).read_text()) for name in POLICY_FILES
    ]
    baseline, merge_gate, sensitive_reviews = copy.deepcopy(payloads)
    status_rule = next(
        rule for rule in baseline["rules"] if rule["type"] == "required_status_checks"
    )
    status_rule["parameters"]["required_status_checks"] = checks
    merge_gate["bypass_actors"] = [
        {"actor_id": merger_id, "actor_type": "User", "bypass_mode": "pull_request"}
    ]
    sensitive_reviews["bypass_actors"] = copy.deepcopy(merge_gate["bypass_actors"])
    policies = [baseline, merge_gate, sensitive_reviews]
    if release_app_id is not None:
        if release_app_id <= 0:
            raise ConfigurationError("The release App ID must be positive.")
        release_actor = {
            "actor_id": release_app_id,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
        for policy in policies:
            policy["bypass_actors"].append(release_actor.copy())
        for filename in ["release-tag-creation.json", "release-tag-protection.json"]:
            policy = json.loads((ROOT / "policies" / filename).read_text())
            policies.append(policy)
        policies[-2]["bypass_actors"].append(release_actor.copy())
    return policies


def inspect_repository(api, repo, merger, check_names, release_app_id=None):
    metadata = api.api(f"repos/{repo}")
    if not metadata.get("permissions", {}).get("admin"):
        raise ConfigurationError(
            "The authenticated account needs repository admin access."
        )
    if metadata.get("archived") or metadata.get("disabled"):
        raise ConfigurationError("The repository is archived or disabled.")
    user = api.api(f"users/{quote(merger, safe='')}")
    if user.get("type") != "User":
        raise ConfigurationError("The merger must be an individual GitHub user.")
    permission = api.api(
        f"repos/{repo}/collaborators/{quote(merger, safe='')}/permission"
    )
    if permission.get("permission") not in ["admin", "maintain", "write"]:
        raise ConfigurationError("The selected merger needs write access or higher.")

    provider = api.api("apps/github-actions")
    if provider.get("slug") != "github-actions" or not provider.get("id"):
        raise ConfigurationError("Could not resolve the GitHub Actions check provider.")
    for branch in ["main", "dev"]:
        sha = api.api(f"repos/{repo}/git/ref/heads/{branch}")["object"]["sha"]
        verify_codeowners(api, repo, sha, merger, branch)
        runs = api.pages(
            f"repos/{repo}/actions/runs?branch={branch}&event=push&head_sha={sha}",
            "workflow_runs",
        )
        latest_runs = {}
        for run in sorted(runs, key=lambda run: (run["created_at"], run["id"])):
            latest_runs[run["workflow_id"]] = run

        jobs = []
        for run in latest_runs.values():
            jobs.extend(
                api.pages(
                    f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest", "jobs"
                )
            )
        for name in check_names:
            matches = [job for job in jobs if job["name"] == name]
            if len(matches) != 1:
                raise ChecksNotReady(
                    f"{branch}: check {name!r} must identify exactly one GitHub Actions job; "
                    "run push CI on the branch head first and use unique job names."
                )
            job = matches[0]
            if job.get("status") != "completed" or job.get("conclusion") != "success":
                raise ChecksNotReady(
                    f"{branch}: check {name!r} has not completed successfully."
                )
    checks = [
        {"context": name, "integration_id": provider["id"]} for name in check_names
    ]
    return build_payloads(checks, user["id"], release_app_id)


def plan_updates(api, repo, payloads):
    existing = api.pages(f"repos/{repo}/rulesets?includes_parents=false")
    plan = []
    for payload in payloads:
        matches = [rule for rule in existing if rule["name"] == payload["name"]]
        if len(matches) > 1:
            raise ConfigurationError(
                f"Duplicate managed ruleset name: {payload['name']}"
            )
        endpoint = f"repos/{repo}/rulesets"
        method = "POST"
        if matches:
            rule = matches[0]
            if (
                rule.get("source_type") != "Repository"
                or rule["source"].lower() != repo.lower()
            ):
                raise ConfigurationError(
                    "Refusing to edit an inherited or unrelated ruleset."
                )
            endpoint += "/" + str(rule["id"])
            method = "PUT"
        plan.append({"method": method, "endpoint": endpoint, "payload": payload})
    return plan


def contains_expected(actual, expected):
    """GitHub may add default parameters and metadata to returned rules."""
    if isinstance(expected, dict):
        if expected.get("type") == "update" and isinstance(actual, dict):
            # GitHub omits the update parameters when fetch and merge is disabled.
            actual = {"parameters": {"update_allows_fetch_and_merge": False}, **actual}
        return isinstance(actual, dict) and all(
            key in actual and contains_expected(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        remaining = list(actual)
        for value in expected:
            for index, candidate in enumerate(remaining):
                if contains_expected(candidate, value):
                    remaining.pop(index)
                    break
            else:
                return False
        return True
    return actual == expected


def apply_updates(api, repo, plan):
    for operation in plan:
        api.api(operation["endpoint"], operation["method"], operation["payload"])
        print("Applied:", operation["payload"]["name"])
    for operation in plan:
        name = operation["payload"]["name"]
        matches = [
            rule
            for rule in api.pages(f"repos/{repo}/rulesets?includes_parents=false")
            if rule["name"] == name
        ]
        if len(matches) != 1:
            raise ConfigurationError(f"Cannot verify ruleset {name!r}.")
        stored = api.api(f"repos/{repo}/rulesets/{matches[0]['id']}")
        if not contains_expected(stored, operation["payload"]):
            raise ConfigurationError(f"Verification failed for {name!r}.")


def initialize_dev(api, repo):
    branches = api.pages(f"repos/{repo}/branches")
    heads = {branch["name"]: branch["commit"]["sha"] for branch in branches}
    if "dev" in heads:
        print(f"{repo}: dev already exists at {heads['dev']}.")
        return
    if "main" not in heads:
        raise ConfigurationError(f"{repo}: main must exist before initializing dev.")
    sha = heads["main"]
    api.api(f"repos/{repo}/git/refs", "POST", {"ref": "refs/heads/dev", "sha": sha})
    print(
        f"{repo}: created dev from main at {sha}. Wait for CI before previewing rulesets."
    )


def detect_repository():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ConfigurationError("Cannot detect origin. Pass --repo OWNER/REPOSITORY.")
    remote = result.stdout.strip()
    match = re.fullmatch(
        r"(?:https://github\.com/|ssh://git@(?P<ssh_host>[\w.-]+)/|"
        r"git@(?P<scp_host>[\w.-]+):)([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)",
        remote,
    )
    if match:
        host = match["ssh_host"] or match["scp_host"]
        if host and host != "github.com":
            config = subprocess.run(
                ["ssh", "-G", host], text=True, capture_output=True, check=False
            )
            if (
                config.returncode
                or "hostname github.com" not in config.stdout.splitlines()
            ):
                raise ConfigurationError(
                    "Origin SSH host does not resolve to github.com. Pass --repo."
                )
        return match[3].removesuffix(".git")
    raise ConfigurationError(
        "Cannot detect a github.com repository from origin. Pass --repo."
    )


def main(argv=None, api=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", help="OWNER/REPOSITORY on github.com (default: checkout origin)"
    )
    parser.add_argument(
        "--merger",
        default="manon42bcn",
        help="Code owner and merger (default: manon42bcn)",
    )
    parser.add_argument(
        "--check",
        action="append",
        dest="checks",
        help="Required GitHub Actions job; repeat to override the default Repository checks",
    )
    parser.add_argument(
        "--release-app-id",
        type=int,
        help="Numeric App ID to enable direct release writes and protect version tags",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check-token",
        action="store_true",
        help="Check repository API access without writing",
    )
    mode.add_argument(
        "--init-dev", action="store_true", help="Create remote dev from main if absent"
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply rulesets; default is read-only preview",
    )
    mode.add_argument(
        "--prepare-codeowners",
        action="store_true",
        help="Write local .github/CODEOWNERS for --merger; no GitHub calls or commits",
    )
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9-]+", args.merger):
        parser.error("--merger must be a GitHub username")
    if args.release_app_id is not None and args.release_app_id <= 0:
        parser.error("--release-app-id must be positive")
    if args.prepare_codeowners:
        if args.repo or args.checks or args.release_app_id is not None:
            parser.error("--prepare-codeowners only takes --merger")
        destination = ROOT / ".github" / "CODEOWNERS"
        destination.parent.mkdir(parents=True, exist_ok=True)
        # This is a managed file. Preview local changes with git diff before committing.
        if destination.is_symlink():
            parser.error("Refusing to write CODEOWNERS through a symbolic link")
        destination.write_text(render_codeowners(args.merger))
        print(
            f"Prepared {destination}. Commit it to main and dev before applying rulesets."
        )
        return 0
    if args.repo is not None and not re.fullmatch(
        r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", args.repo
    ):
        parser.error("--repo must be OWNER/REPOSITORY, without a URL")
    if args.checks is not None and any(not name.strip() for name in args.checks):
        parser.error("At least one nonempty --check is required")
    if args.init_dev and (args.checks or args.release_app_id is not None):
        parser.error("--init-dev does not use --check or --release-app-id")
    api = api or GitHub()
    try:
        if args.repo is None:
            args.repo = detect_repository()
        if args.check_token:
            metadata = api.api(f"repos/{args.repo}")
            if not metadata.get("permissions", {}).get("admin"):
                raise ConfigurationError(
                    "The authenticated account needs repository admin access."
                )
            api.api(f"repos/{args.repo}/git/ref/heads/main")
            api.api(f"repos/{args.repo}/actions/runs?per_page=1")
            api.api(f"repos/{args.repo}/rulesets/history?per_page=1")
            print(
                f"{args.repo}: Contents read, Actions read and Administration write verified."
            )
            print(
                "Branch creation verifies Contents write and any required Workflows write access."
            )
            return 0
        if args.init_dev:
            initialize_dev(api, args.repo)
            return 0
        checks = list(dict.fromkeys(args.checks or ["Repository checks"]))
        payloads = inspect_repository(
            api, args.repo, args.merger, checks, args.release_app_id
        )
        plan = plan_updates(api, args.repo, payloads)
        print(
            json.dumps(
                {"repository": args.repo, "apply": args.apply, "operations": plan},
                indent=2,
            )
        )
        if not args.apply:
            print("Preview only. Repeat with --apply to activate these rulesets.")
            return 0
        apply_updates(api, args.repo, plan)
        print(
            "All managed rulesets are active and verified. No repository files or branches were changed."
        )
        return 0
    except (ConfigurationError, FileNotFoundError, KeyError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(
            "No further operations attempted. If an apply failed partway through, inspect "
            "Settings → Rules → Rulesets and rerun after resolving the error.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
