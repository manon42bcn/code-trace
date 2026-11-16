#!/usr/bin/env python3
"""Initialize the GitHub repository at origin."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import configure_repository as policy
import release


def bootstrap(repo, main, version, branches):
    if "dev" in branches:
        print("dev already exists. Checking its release configuration.", flush=True)
    with TemporaryDirectory(prefix="template-release-") as directory:
        url = f"https://github.com/{repo}.git"
        credentials = [
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
        ]
        release.run(
            "git",
            *credentials,
            "clone",
            "--no-tags",
            "--branch",
            "main",
            url,
            directory,
        )
        previous = Path.cwd()
        try:
            os.chdir(directory)
            if release.git("rev-parse", "HEAD") != main:
                raise ValueError(
                    "main changed during setup. Run the initializer again."
                )
            for file in [".github/workflows/release.yml", "scripts/release.py"]:
                if not Path(file).is_file():
                    raise ValueError(f"Push {file} to main before continuing.")
            settings = release.config()
            if "dev" in branches:
                release.git("checkout", "--detach", branches["dev"])
                release.git("merge-base", main, branches["dev"])
                settings = release.config()
                if not release.DEV_VERSION.fullmatch(release.project_version(settings)):
                    raise ValueError(
                        "Set a development version on the existing dev through a PR."
                    )
                _, *sections = release.changelog_sections()
                if not sections or not release.is_unreleased(sections[0]):
                    raise ValueError("Add Unreleased on the existing dev through a PR.")
                return
            release.open_cycle(settings, version)
            # Some projects already have the desired development files on main.
            if release.git("status", "--porcelain", "--untracked-files=all"):
                release.commit_version(settings, f"Start {version}")
            if (
                release.git(*credentials, "ls-remote", "origin", release.MAIN).split()[
                    0
                ]
                != main
            ):
                raise ValueError(
                    "main changed during setup. Run the initializer again."
                )
            release.run(
                "git",
                *credentials,
                "push",
                f"--force-with-lease={release.DEV}:",
                "origin",
                f"HEAD:{release.DEV}",
            )
        finally:
            os.chdir(previous)


def set_variable(repo, name, value):
    release.run("gh", "variable", "set", name, "--repo", repo, "--body", value)


def initialize(args):
    mode = os.getenv("RELEASE_AUTOMATION_ENABLED", "false")
    if mode not in {"true", "false"}:
        raise ValueError("RELEASE_AUTOMATION_ENABLED must be true or false.")
    automatic = mode == "true"
    merger = os.getenv("RELEASE_MERGER", "manon42bcn")
    if not re.fullmatch(r"[A-Za-z0-9-]+", merger):
        raise ValueError("Provide a valid RELEASE_MERGER.")
    app_id = None
    if automatic:
        app_id = int(os.environ["RELEASE_APP_ID"])
        client_id = os.environ["RELEASE_APP_CLIENT_ID"]
        pem = Path(os.environ["RELEASE_APP_PRIVATE_KEY_FILE"]).expanduser()
        version = os.getenv("RELEASE_INITIAL_VERSION", "0.1.0-dev.0")
        if app_id <= 0 or not re.fullmatch(r"[A-Za-z0-9_.-]+", client_id):
            raise ValueError(
                "Provide a positive RELEASE_APP_ID and a valid RELEASE_APP_CLIENT_ID."
            )
        if not release.DEV_VERSION.fullmatch(version):
            raise ValueError("Provide an initial version such as 0.1.0-dev.0.")
        with pem.open("rb") as key:
            if not re.fullmatch(
                rb"-----BEGIN (?:RSA )?PRIVATE KEY-----\r?\n", key.readline()
            ):
                raise ValueError(
                    "RELEASE_APP_PRIVATE_KEY_FILE must point to a PEM private key."
                )

    repo = policy.detect_repository()
    api = policy.GitHub()
    metadata = api.api(f"repos/{repo}")
    if (
        not metadata.get("permissions", {}).get("admin")
        or metadata.get("default_branch") != "main"
        or metadata.get("archived")
        or metadata.get("disabled")
    ):
        raise ValueError(
            "Setup requires admin access to an active repository with main as its default branch."
        )
    if automatic:
        for endpoint, permission in [
            ("secrets/public-key", "Secrets"),
            ("variables?per_page=1", "Variables"),
        ]:
            try:
                api.api(f"repos/{repo}/actions/{endpoint}")
            except policy.ConfigurationError as error:
                raise policy.ConfigurationError(
                    f"Cannot access Actions {permission.lower()} in {repo}. Verify the active gh credential "
                    f"(GH_ADMIN_TOKEN or GH_TOKEN) selects this repository and grants "
                    f"{permission}: Read and write. GitHub reported: {error}"
                ) from error
    branches = {
        b["name"]: b["commit"]["sha"] for b in api.pages(f"repos/{repo}/branches")
    }
    main = branches["main"]
    policy.verify_codeowners(api, repo, main, merger, "main")
    if "dev" in branches:
        policy.verify_codeowners(api, repo, branches["dev"], merger, "dev")

    if automatic:
        print(f"Initializing {repo} with release App ID {app_id}.", flush=True)
        bootstrap(repo, main, version, branches)
    else:
        policy.initialize_dev(api, repo)
    checks = list(dict.fromkeys(args.check or ["Repository checks"]))
    deadline = time.monotonic() + args.wait_seconds
    while True:
        try:
            payloads = policy.inspect_repository(api, repo, merger, checks, app_id)
            break
        except policy.ChecksNotReady as error:
            if time.monotonic() >= deadline:
                raise
            print(f"Waiting for CI: {error}", flush=True)
            time.sleep(min(15, max(0, deadline - time.monotonic())))

    plan = policy.plan_updates(api, repo, payloads)
    if not automatic:
        policy.apply_updates(api, repo, plan)
        print(f"{repo}: manual release setup complete.")
        return

    if not metadata["allow_merge_commit"] or metadata["delete_branch_on_merge"]:
        api.api(
            f"repos/{repo}",
            "PATCH",
            {"allow_merge_commit": True, "delete_branch_on_merge": False},
        )
    with pem.open("rb") as key:
        subprocess.run(
            ["gh", "secret", "set", "RELEASE_APP_PRIVATE_KEY", "--repo", repo],
            stdin=key,
            check=True,
        )
    set_variable(repo, "RELEASE_APP_CLIENT_ID", client_id)
    policy.apply_updates(api, repo, plan)
    set_variable(repo, "RELEASE_AUTOMATION_ENABLED", "true")
    print(f"{repo}: automated releases enabled.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="append", help="Required CI job, repeat for multiple jobs"
    )
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()
    try:
        initialize(args)
    except (
        policy.ConfigurationError,
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
