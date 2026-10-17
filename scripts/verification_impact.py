"""Fail-closed CI selection: only ordinary documentation may use Quick."""

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def verification_mode(paths: list[str]) -> str:
    if not paths:
        return "full"
    for name in paths:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            return "full"
        # These govern architecture, security or test policy, rather than ordinary prose.
        if name in {
            "AGENTS.md",
            "CONTRIBUTING.md",
            "docs/development/testing-standard.md",
            "docs/development/development-workflow.md",
            "docs/development/release-process.md",
        } or name.startswith(("docs/architecture/", "docs/requirements/", "docs/decisions/")):
            return "full"
        ordinary_markdown = path.suffix == ".md" and (
            name.startswith(("docs/", "tasks/"))
            or name in {"README.md", "PROJECT_STATE.md", "CHANGELOG.md"}
        )
        task_metadata = path.suffix == ".yaml" and (
            name.startswith(("tasks/active/", "tasks/completed/"))
            or name in {"tasks/template.yaml", "docs/development/roadmap.yaml"}
        )
        if not (ordinary_markdown or task_metadata):
            return "full"
    return "quick"


def changed_paths(event_name: str, event: dict, root: Path = ROOT) -> list[str]:
    if event_name == "push":
        base, head = event.get("before", ""), event.get("after", "")
    elif event_name == "pull_request":
        request = event.get("pull_request", {})
        base, head = request.get("base", {}).get("sha", ""), request.get("head", {}).get("sha", "")
    else:
        return []
    if any(not re.fullmatch(r"[a-f0-9]{40}", sha) or sha == "0" * 40 for sha in (base, head)):
        return []

    def git(arguments: list[str]) -> bytes:
        executable = shutil.which("git")
        if executable is None:
            raise OSError("Git required for change classification")
        return subprocess.run(  # noqa: S603 - fixed git, validated hashes, no shell
            [executable, "-C", str(root), *arguments],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout

    try:
        if event_name == "pull_request":
            base = git(["merge-base", base, head]).decode().strip()
        return [
            name.decode("utf-8")
            for name in git(["diff", "--name-only", "--no-renames", "-z", base, head, "--"]).split(
                b"\0"
            )
            if name
        ]
    except (subprocess.SubprocessError, UnicodeError, OSError):
        return []  # unavailable comparison history => Full, never a successful skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--event-name", required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.event.read_text(encoding="utf-8"))
        paths = changed_paths(args.event_name, data)
        mode = verification_mode(paths)
    except (ValueError, OSError, AttributeError, TypeError):
        mode, paths = "full", []
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"mode={mode}\n")
    print(json.dumps({"mode": mode, "changed_files": len(paths)}))


if __name__ == "__main__":
    main()
