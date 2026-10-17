from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from docx import Document

from scripts.generate_demo_fixture import ROOT, create_fixture


def test_task0020_fixture_is_explicitly_synthetic_and_contains_rule_example(tmp_path: Path) -> None:
    output = (
        ROOT
        / ".verification"
        / "task0020-test"
        / tmp_path.name
        / f"{uuid.uuid4().hex}.docx"
    ).resolve()
    try:
        path, digest = create_fixture(output)
        paragraphs = [item.text for item in Document(path).paragraphs]
        joined = "\n".join(paragraphs)
        assert "不对应任何真实采购项目" in joined
        assert "投标人必须在本市注册" in joined
        assert len(digest) == 64
    finally:
        output.unlink(missing_ok=True)
        output.parent.rmdir()
        output.parent.parent.rmdir()


def test_task0020_fixture_refuses_outputs_outside_verification() -> None:
    with pytest.raises(ValueError, match="must stay under .verification"):
        create_fixture(ROOT / "README.md")
