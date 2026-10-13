"""TASK0017: documentation cannot suppress a runtime/security verification gate."""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from verification_impact import changed_paths, verification_mode

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "paths,expected",
    [
        (
            ["docs/development/TASK-0006-design.md", "tasks/active/TASK-0006-legal-retrieval.yaml"],
            "quick",
        ),
        (["PROJECT_STATE.md", "tasks/reviews/TASK-0006.md"], "quick"),
        (["docs/development/roadmap.yaml"], "quick"),
        (["README.md", "src/bidding_compliance/api/app.py"], "full"),
        (["tests/test_legal_runs.py"], "full"),
        (["contracts/openapi.yaml"], "full"),
        (["config/legal/manifest.json"], "full"),
        (["knowledge/legal/索引.md"], "full"),
        (["requirements-dev.lock"], "full"),
        (["scripts/verify.ps1"], "full"),
        ([".github/workflows/verify.yml"], "full"),
        (["AGENTS.md"], "full"),
        (["docs/development/testing-standard.md"], "full"),
        (["docs/development/development-workflow.md"], "full"),
        (["docs/architecture/security.md"], "full"),
        (["docs/decisions/ADR-0011-development-and-validation.md"], "full"),
        (["unknown-file.md"], "full"),
        (["../docs/test.md"], "full"),
        ([], "full"),
    ],
)
def test_ci_requires_full_for_code_security_and_unknown_changes(paths, expected):
    assert verification_mode(paths) == expected


def test_missing_or_initial_comparison_history_falls_back_to_full(tmp_path):
    for event_name, event in [
        ("push", {"before": "0" * 40, "after": "a" * 40}),
        ("push", {"before": "a" * 40, "after": "b" * 40}),
        ("pull_request", {}),
        ("workflow_dispatch", {}),
    ]:
        assert verification_mode(changed_paths(event_name, event, tmp_path)) == "full"


def test_real_git_comparison_includes_deleted_code_despite_document_rename(tmp_path):
    executable = shutil.which("git")
    assert executable

    def git(*arguments):
        return subprocess.run(  # noqa: S603 - controlled commands in isolated temporary repo
            [executable, "-C", str(tmp_path), *arguments],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()

    git("init")
    git("config", "user.name", "verification")
    git("config", "user.email", "verification@example.invalid")
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    code = tmp_path / "src/module.py"
    code.write_text("value = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "synthetic baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / "docs/note.md").write_text("synthetic note\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "synthetic documentation")
    head = git("rev-parse", "HEAD")
    assert (
        verification_mode(changed_paths("push", {"before": base, "after": head}, tmp_path))
        == "quick"
    )
    event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    assert verification_mode(changed_paths("pull_request", event, tmp_path)) == "quick"
    code.replace(tmp_path / "docs/renamed.md")
    git("add", ".")
    git("commit", "-m", "synthetic code deletion and rename")
    after = git("rev-parse", "HEAD")
    paths = changed_paths("push", {"before": head, "after": after}, tmp_path)
    assert "src/module.py" in paths and verification_mode(paths) == "full"


def run_mode(arguments):
    executable = shutil.which("pwsh")
    assert executable, "PowerShell7 is required for validation-profile acceptance"
    environment = os.environ.copy()
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(  # noqa: S603 - fixed repository script, controlled test arguments
        [executable, "-NoProfile", "-File", str(ROOT / "scripts/verify.ps1"), *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["-Mode", "Focused"],
        ["-Mode", "Focused", "-TestPaths", "../AGENTS.md"],
        ["-Mode", "Focused", "-TestPaths", "tests/conftest.py"],
        ["-Mode", "Full", "-TestPaths", "tests/test_legal_runs.py"],
    ],
)
def test_invalid_selection_cannot_narrow_or_claim_full_verification(arguments):
    result = run_mode(arguments)
    assert result.returncode != 0
    assert "PASS:" not in result.stdout


def test_quick_mode_preserves_existing_full_test_evidence():
    path = ROOT / ".verification/pytest-result.xml"
    before = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    result = run_mode(["-Mode", "Quick"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Quick repository/contract/secret checks only" in result.stdout
    assert "[4/6]" not in result.stdout and "Real backend startup" not in result.stdout
    after = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    assert before == after
