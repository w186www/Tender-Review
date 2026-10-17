"""The engineering gate must fail on errors, not just pass on current files."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from generate_state import check_state
from verify_contracts import (
    check_delivery_units,
    check_dependencies,
    check_product_traceability,
    check_roadmap,
    check_tasks,
    load_contracts,
    load_openapi,
    load_yaml,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("corruption", ["syntax", "duplicate", "reference"])
def test_invalid_openapi_is_rejected(tmp_path, corruption):
    folder = tmp_path / "contracts"
    folder.mkdir()
    api = load_yaml(ROOT / "contracts/openapi.yaml")
    text = (ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8")
    if corruption == "syntax":
        text += "\n[broken YAML"
    elif corruption == "duplicate":
        text += "\nopenapi: 3.1.0\n"
    else:
        api["paths"]["/projects"]["post"]["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ] = "#/components/schemas/Missing"
        text = yaml.safe_dump(api)
    (folder / "openapi.yaml").write_text(text, encoding="utf-8")
    assert load_openapi(tmp_path)[1]


@pytest.mark.parametrize("corruption", ["type", "ref", "fragment", "remote"])
def test_invalid_schema_is_rejected_without_remote_fetch(tmp_path, corruption):
    folder = tmp_path / "contracts/schemas"
    folder.mkdir(parents=True)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://bidding-compliance.local/schemas/probe.schema.json",
        "type": "object",
    }
    if corruption == "type":
        schema["type"] = "not-a-type"
    else:
        schema["$ref"] = {
            "ref": "missing.schema.json",
            "fragment": "#/$defs/missing",
            "remote": "https://unregistered.invalid/no-network.schema.json",
        }[corruption]
    (folder / "probe.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    assert load_contracts(tmp_path)[2]


@pytest.mark.parametrize("corruption", ["yaml", "status", "id", "missing_evidence"])
def test_invalid_task_is_rejected(tmp_path, corruption):
    task = load_yaml(ROOT / "tasks/template.yaml")
    task["task_id"] = "TASK-0002"
    task["depends_on"] = []
    task["read_first"] = ["AGENTS.md", "PROJECT_STATE.md", "docs/index.md"]
    for name in task["read_first"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    directory = tmp_path / "tasks/active"
    if corruption == "status":
        task["status"] = "done-ish"
    elif corruption == "id":
        task["related_requirements"] = ["FR-999"]
    elif corruption == "missing_evidence":
        task["status"] = "completed"
        directory = tmp_path / "tasks/completed"
    directory.mkdir(parents=True)
    text = yaml.safe_dump(task)
    if corruption == "yaml":
        text += "\n[broken YAML"
    (directory / "TASK-0002-fixture.yaml").write_text(text, encoding="utf-8")
    schema = json.loads((ROOT / "contracts/schemas/task.schema.json").read_text(encoding="utf-8"))
    declared = {"NFR-009"}
    assert check_tasks(tmp_path, declared, schema)[1]


def test_valid_task_remains_valid_after_completion_move(tmp_path):
    task = load_yaml(ROOT / "tasks/template.yaml")
    task["task_id"] = "TASK-0099"
    for name in task["read_first"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    active = tmp_path / "tasks/active/TASK-0099-fixture.yaml"
    active.parent.mkdir(parents=True)
    active.write_text(yaml.safe_dump(task), encoding="utf-8")
    schema = json.loads((ROOT / "contracts/schemas/task.schema.json").read_text(encoding="utf-8"))
    assert not check_tasks(tmp_path, {"NFR-009"}, schema)[1]
    task["status"] = "completed"
    for check in task["acceptance_checks"]:
        check["evidence"] = ["docs/index.md"]
    active.write_text(yaml.safe_dump(task), encoding="utf-8")
    completed = tmp_path / "tasks/completed/TASK-0099-fixture.yaml"
    completed.parent.mkdir(parents=True)
    active.rename(completed)
    assert not check_tasks(tmp_path, {"NFR-009"}, schema)[1]


def test_cycles_and_unfinished_dependencies_are_rejected():
    cycle = {
        "TASK-0001": {"depends_on": ["TASK-0002"], "status": "planned"},
        "TASK-0002": {"depends_on": ["TASK-0001"], "status": "planned"},
    }
    assert check_dependencies(cycle, "task")
    unfinished = {
        "TASK-0001": {"depends_on": [], "status": "planned"},
        "TASK-0002": {"depends_on": ["TASK-0001"], "status": "completed"},
    }
    assert check_dependencies(unfinished, "task")


@pytest.mark.parametrize("corruption", ["uncovered_requirement", "unassigned_task"])
def test_roadmap_cannot_silently_drop_scope(tmp_path, corruption):
    roadmap = load_yaml(ROOT / "docs/development/roadmap.yaml")
    declared = set()
    for milestone in roadmap["milestones"]:
        declared.update(milestone["related_requirements"] + milestone["related_acceptance"])
    tasks = {}
    for folder in ("tasks/active", "tasks/completed"):
        for path in (ROOT / folder).glob("TASK-*.yaml"):
            task = load_yaml(path)
            tasks[task["task_id"]] = task
    if corruption == "uncovered_requirement":
        milestone = next(item for item in roadmap["milestones"] if item["id"] == "M3")
        milestone["related_requirements"].remove("FR-014")
    else:
        milestone = next(item for item in roadmap["milestones"] if item["id"] == "M1")
        milestone["tasks"].remove("TASK-0002")
    target = tmp_path / "docs/development/roadmap.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(yaml.safe_dump(roadmap), encoding="utf-8")
    assert check_roadmap(tmp_path, declared, tasks)


def test_product_delivery_units_cover_all_units_and_resolve_task_mapping():
    roadmap = load_yaml(ROOT / "docs/development/roadmap.yaml")
    tasks = {}
    for folder in ("tasks/active", "tasks/completed"):
        for path in (ROOT / folder).glob("TASK-*.yaml"):
            task = load_yaml(path)
            tasks[task["task_id"]] = task

    assert check_delivery_units(roadmap, tasks) == []


def test_product_traceability_covers_all_requirements_and_unit_evidence(tmp_path):
    source = load_yaml(ROOT / "docs/development/product-delivery-traceability.yaml")
    target = tmp_path / "docs/development/product-delivery-traceability.yaml"
    target.parent.mkdir(parents=True)
    (tmp_path / "docs/development/roadmap.yaml").write_text(
        (ROOT / "docs/development/roadmap.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "docs/development/product-delivery-validation.md").write_text(
        "# G3 evidence\n", encoding="utf-8"
    )

    target.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    declared = set(source["requirements"])
    assert check_product_traceability(tmp_path, declared) == []

    source["requirements"].pop("FR-001")
    target.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    assert check_product_traceability(tmp_path, declared)

    source["requirements"]["FR-001"] = ["U99"]
    target.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    assert check_product_traceability(tmp_path, declared)


@pytest.mark.parametrize(
    "corruption", ["unknown_dependency", "cycle", "unknown_task", "missing_unit"]
)
def test_product_delivery_unit_graph_rejects_invalid_mapping(corruption):
    roadmap = load_yaml(ROOT / "docs/development/roadmap.yaml")
    tasks = {}
    for folder in ("tasks/active", "tasks/completed"):
        for path in (ROOT / folder).glob("TASK-*.yaml"):
            task = load_yaml(path)
            tasks[task["task_id"]] = task

    units = roadmap["product_delivery_units"]
    if corruption == "unknown_dependency":
        units[1]["depends_on"] = ["U99"]
    elif corruption == "cycle":
        units[0]["depends_on"] = ["U02"]
    elif corruption == "unknown_task":
        units[0]["tasks"] = ["TASK-9999"]
    else:
        roadmap["product_delivery_units"] = units[:-1]

    errors = check_delivery_units(roadmap, tasks)
    assert errors


def test_state_drift_is_rejected(tmp_path):
    schema = tmp_path / "contracts/schemas/compliance-state.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text(
        (ROOT / "contracts/schemas/compliance-state.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    state = tmp_path / "src/bidding_compliance/graph/state.py"
    state.parent.mkdir(parents=True)
    state.write_text("# stale definition\n", encoding="utf-8")
    assert not check_state(tmp_path)


def test_empty_test_suite_has_nonzero_exit(tmp_path):
    empty = tmp_path / "empty_tests"
    empty.mkdir()
    result = subprocess.run(  # noqa: S603 -- fixed local interpreter and isolated test directory
        [sys.executable, "-m", "pytest", "-o", "addopts=", str(empty)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED
