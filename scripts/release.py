#!/usr/bin/env python3
"""Prepare tested release commits and publish them from a separate runner."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

DEV_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-dev\.0")
CHANGELOG = Path("CHANGELOG.md")
MAIN = "refs/heads/main"
DEV = "refs/heads/dev"


def run(*args):
    subprocess.run(args, check=True)


def read(*args):
    return subprocess.check_output(args, text=True).strip()


def git(*args):
    return read("git", *args)


def remote_ref(ref):
    result = git("ls-remote", "origin", ref)
    return result.split()[0] if result else None


def ancestor(older, newer):
    result = subprocess.run(["git", "merge-base", "--is-ancestor", older, newer])
    if result.returncode > 1:
        result.check_returncode()
    return result.returncode == 0


def config():
    value = json.loads(Path("release.json").read_text())
    files = value["version_files"]
    if not files or not value["test"]:
        raise ValueError("release.json requires version files and test commands.")
    for name in files:
        path = Path(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or any(part.lower() == ".git" for part in path.parts)
            or not path.resolve().is_relative_to(Path.cwd())
        ):
            raise ValueError(f"Invalid version file: {name}")
    return value


def version_document(name):
    path = Path(name)
    if path.name not in {"package.json", "package-lock.json"}:
        return None, []
    doc = json.loads(path.read_text())
    roots = [doc]
    if path.name == "package-lock.json" and "packages" in doc:
        roots.append(doc["packages"][""])
    return doc, roots


def read_pyproject(path):
    content = path.read_bytes().decode("utf-8")
    document = tomllib.loads(content)
    version = document.get("project", {}).get("version")
    if not isinstance(version, str):
        raise ValueError(f"{path} requires a static [project] version.")
    return content, document, version


def update_pyproject(path, version):
    content, expected, _ = read_pyproject(path)
    expected["project"]["version"] = version
    section = re.search(
        r"(?m)^[ \t]*\[project\][ \t]*(?:#[^\r\n]*)?\r?\n"
        r"(?P<body>.*?)(?=^[ \t]*\[|\Z)",
        content,
        re.DOTALL,
    )
    if section:
        body, count = re.subn(
            r"""(?m)^([ \t]*version[ \t]*=[ \t]*)(["'])([^"'\r\n]*)\2(?=[ \t]*(?:#|\r?$))""",
            lambda match: match[1] + match[2] + version + match[2],
            section["body"],
        )
        updated = (
            content[: section.start("body")] + body + content[section.end("body") :]
        )
        if count == 1 and tomllib.loads(updated) == expected:
            return updated.encode("utf-8")
    raise ValueError(
        f'{path} requires version = "..." on its own line under [project].'
    )


def project_version(settings):
    values = set()
    for name in settings["version_files"]:
        path = Path(name)
        if path.name == "pyproject.toml":
            values.add(read_pyproject(path)[2])
            continue
        _, roots = version_document(name)
        if roots:
            values.update(root["version"] for root in roots)
        else:
            values.add(Path(name).read_text().strip())
    if len(values) != 1:
        raise ValueError("The project version files disagree.")
    return values.pop()


def write_version(settings, version):
    updates = {}
    for name in settings["version_files"]:
        path = Path(name)
        if path.name == "pyproject.toml":
            updates[path] = update_pyproject(path, version)
            continue
        doc, roots = version_document(name)
        if roots:
            for root in roots:
                root["version"] = version
            content = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
            updates[path] = content.encode("utf-8")
        else:
            updates[path] = (version + "\n").encode("utf-8")
    for path, content in updates.items():
        path.write_bytes(content)


def changelog_sections():
    content = CHANGELOG.read_text() if CHANGELOG.exists() else "# Changelog\n\n"
    return re.split(r"(?m)^## ", content)


def open_cycle(settings, version):
    if not DEV_VERSION.fullmatch(version):
        raise ValueError(
            "Development version must have the form MAJOR.MINOR.PATCH-dev.0."
        )
    write_version(settings, version)
    intro, *sections = changelog_sections()
    if not sections or not is_unreleased(sections[0]):
        sections.insert(0, "Unreleased\n\n")
    if not intro.endswith("\n\n"):
        intro = intro.rstrip() + "\n\n" if intro.strip() else ""
    CHANGELOG.write_text(intro + "".join(f"## {section}" for section in sections))


def is_unreleased(section):
    return bool(
        re.fullmatch(
            r"Unreleased|\d+\.\d+\.\d+ \(Unreleased\)", section.partition("\n")[0]
        )
    )


def close_cycle(settings, version, date):
    intro, *sections = changelog_sections()
    if not sections or not is_unreleased(sections[0]):
        raise ValueError("The first changelog section must be Unreleased.")
    if any(
        section.partition("\n")[0].split(" - ")[0] == version
        for section in sections[1:]
    ):
        raise ValueError(f"The changelog already contains {version}.")
    _, _, notes = sections[0].partition("\n")
    notes = notes.strip() or "No changelog entries."
    sections[0] = f"{version} - {date}\n\n{notes}\n\n"
    CHANGELOG.write_text(intro + "".join(f"## {section}" for section in sections))
    write_version(settings, version)


def commit_version(settings, message):
    git("add", "--", *settings["version_files"], str(CHANGELOG))
    git(
        "-c",
        "user.name=Release automation",
        "-c",
        "user.email=release-automation@users.noreply.github.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        message,
    )
    return git("rev-parse", "HEAD")


def promotion_head(promotion, expected_dev):
    commit, *parents = git("rev-list", "--parents", "-n", "1", promotion).split()
    if commit != promotion or len(parents) != 2 or parents[1] != expected_dev:
        raise ValueError(
            "Promote dev to main using a merge commit with the PR head as its second parent."
        )
    return parents[1]


def release_notes(version):
    _, *sections = changelog_sections()
    for section in sections:
        heading, _, body = section.partition("\n")
        if heading.split(" - ")[0] == version:
            return body.strip() + "\n"
    raise ValueError(f"No changelog section for {version}.")


def prepare(output):
    promotion = os.environ["PROMOTION_SHA"]
    promotion_head(promotion, os.environ["PROMOTED_DEV"])
    if git("rev-parse", "HEAD") != promotion:
        raise ValueError("Expected the promotion commit at checkout.")
    settings = config()
    match = DEV_VERSION.fullmatch(project_version(settings))
    if not match:
        raise ValueError("Prepare MAJOR.MINOR.PATCH-dev.0 on dev before promoting.")
    major, minor, patch = match.groups()
    version = f"{major}.{minor}.{patch}"
    next_version = f"{major}.{minor}.{int(patch) + 1}-dev.0"
    tag = f"v{version}"
    existing = git("tag", "--list", tag)
    main = git("rev-parse", "origin/main")
    if existing:
        stable = git("rev-list", "--parents", "-n", "1", tag).split()
        if stable[1:] != [promotion] or not ancestor(stable[0], main):
            raise ValueError(f"{tag} belongs to a different release.")
        stable = stable[0]
        git("checkout", "--detach", stable)
        if project_version(settings) != version:
            raise ValueError(f"{tag} has a different project version.")
    else:
        if main != promotion:
            raise ValueError(
                "main advanced past the promotion. Inspect main before retrying."
            )
        date = git("show", "-s", "--format=%cI", promotion)[:10]
        close_cycle(settings, version, datetime.date.fromisoformat(date))
        stable = commit_version(settings, f"Release {tag}")

    output.mkdir(parents=True)
    notes = release_notes(version)
    for command in settings["test"] + settings.get("package", []):
        run(*command)
    if git("rev-parse", "HEAD") != stable or git(
        "status", "--porcelain", "--untracked-files=no"
    ):
        raise ValueError("Tests or packaging changed the stable checkout.")
    assets = output / "assets"
    assets.mkdir()
    for pattern in settings.get("assets", []):
        paths = sorted(Path().glob(pattern))
        if not paths:
            raise ValueError(f"No release assets matched {pattern!r}.")
        for path in paths:
            if (
                not path.is_file()
                or path.is_symlink()
                or not path.resolve().is_relative_to(Path.cwd())
            ):
                raise ValueError(f"Invalid release asset: {path}")
            if (assets / path.name).exists() or not re.fullmatch(
                r"[A-Za-z0-9_][A-Za-z0-9._-]*", path.name
            ):
                raise ValueError(
                    f"Invalid or duplicate release asset name: {path.name}"
                )
            shutil.copyfile(path, assets / path.name)

    open_cycle(settings, next_version)
    development = commit_version(settings, f"Start {next_version}")
    git("bundle", "create", str(output / "commits.bundle"), "HEAD", f"^{promotion}")
    (output / "notes.md").write_text(notes)
    (output / "release.json").write_text(
        json.dumps(
            {
                "tag": tag,
                "stable": stable,
                "development": development,
                "assets": sorted(p.name for p in assets.iterdir()),
            }
        )
    )


def publish(output):
    promotion = os.environ["PROMOTION_SHA"]
    promoted_dev = promotion_head(promotion, os.environ["PROMOTED_DEV"])
    data = json.loads((output / "release.json").read_text())
    stable, development, tag = (data[key] for key in ("stable", "development", "tag"))
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Invalid release tag.")
    tag_ref = f"refs/tags/{tag}"
    git("fetch", "--no-tags", str(output / "commits.bundle"), "HEAD")
    for sha, parent in [(stable, promotion), (development, stable)]:
        if git("rev-list", "--parents", "-n", "1", sha).split() != [sha, parent]:
            raise ValueError(
                "Release commits do not descend from the expected promotion."
            )

    current_tag = remote_ref(tag_ref)
    if current_tag is None:
        # Both updates succeed together and neither can overwrite a concurrent update.
        run(
            "git",
            "push",
            "--atomic",
            f"--force-with-lease={MAIN}:{promotion}",
            f"--force-with-lease={tag_ref}:",
            "origin",
            f"{stable}:{MAIN}",
            f"{stable}:{tag_ref}",
        )
    else:
        git("fetch", "--no-tags", "origin", f"{MAIN}:refs/remotes/origin/main", tag_ref)
        if git("rev-parse", f"{current_tag}^{{commit}}") != stable or not ancestor(
            stable, "origin/main"
        ):
            raise ValueError(f"{tag} does not identify this release on main.")

    publish_release(tag, output, data["assets"])

    current_dev = remote_ref(DEV)
    if current_dev == promoted_dev:
        run(
            "git",
            "push",
            f"--force-with-lease={DEV}:{promoted_dev}",
            "origin",
            f"{development}:{DEV}",
        )
    else:
        git("fetch", "--no-tags", "origin", DEV)
        if not ancestor(stable, "FETCH_HEAD"):
            raise ValueError(
                "dev advanced independently. Synchronize the stable commit through a PR."
            )
        # A successful prior run or its descendant already contains the next-cycle commit.
        expected_tree = git("rev-parse", f"{development}^{{tree}}")
        for sha in git(
            "rev-list", "--ancestry-path", f"{stable}..FETCH_HEAD"
        ).splitlines():
            if git("rev-parse", f"{sha}^{{tree}}") == expected_tree:
                return
        raise ValueError(
            "dev contains the stable commit. Verify the next version and changelog in a PR."
        )


def publish_release(tag, output, asset_names):
    repo = os.environ["GH_REPO"]
    releases = read(
        "gh",
        "api",
        "--paginate",
        f"repos/{repo}/releases?per_page=100",
        "--jq",
        f'.[] | select(.tag_name == "{tag}") | @json',
    )
    matches = [json.loads(line) for line in releases.splitlines()]
    if len(matches) > 1:
        raise ValueError(f"Multiple releases found for {tag}.")
    expected = set(asset_names)
    if matches and not matches[0]["draft"]:
        actual = {
            asset["name"]
            for asset in matches[0]["assets"]
            if asset["state"] == "uploaded"
        }
        if matches[0]["prerelease"] or actual != expected:
            raise ValueError(
                f"Published release {tag} does not have the expected stable assets."
            )
        return

    notes = str(output / "notes.md")
    if not matches:
        run(
            "gh",
            "release",
            "create",
            tag,
            "--verify-tag",
            "--draft",
            "--title",
            tag,
            "--notes-file",
            notes,
        )
    else:
        previous = {asset["name"] for asset in matches[0]["assets"]}
        if previous - expected:
            raise ValueError(
                f"Draft {tag} has unexpected assets. Review it before retrying."
            )
    if expected:
        paths = [str(output / "assets" / name) for name in asset_names]
        run("gh", "release", "upload", tag, *paths, "--clobber")
    run(
        "gh",
        "release",
        "edit",
        tag,
        "--draft=false",
        "--prerelease=false",
        "--title",
        tag,
        "--notes-file",
        notes,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "publish"])
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        {"prepare": prepare, "publish": publish}[args.phase](args.output.resolve())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
