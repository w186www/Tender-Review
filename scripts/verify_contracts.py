"""Validate contracts and task evidence without fetching remote Schema resources."""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import yaml
from generate_state import check_state
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = [
    "AGENTS.md",
    "README.md",
    "PROJECT_STATE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    ".github/workflows/verify.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/index.md",
    "docs/development/roadmap.yaml",
    "docs/development/roadmap.md",
    "docs/development/product-delivery-traceability.yaml",
    "docs/requirements/functional.md",
    "docs/requirements/security.md",
    "docs/requirements/non-functional.md",
    "docs/requirements/acceptance.md",
    "docs/architecture/system.md",
    "docs/architecture/langgraph.md",
    "docs/architecture/model-gateway.md",
    "contracts/openapi.yaml",
    "contracts/schemas/compliance-state.schema.json",
    "contracts/schemas/risk.schema.json",
    "contracts/schemas/evidence.schema.json",
    "contracts/schemas/task.schema.json",
    "contracts/examples/manifest.yaml",
    "tasks/template.yaml",
    "evals/thresholds.yaml",
    "requirements-dev.lock",
    "contracts/VERSION.md",
]
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".verification",
    "tmp",
    "secrets",
}


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently changing a contract."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise ValueError(f"duplicate YAML key: {key}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml(path: Path):
    # This loader inherits SafeLoader and only adds rejection of duplicate keys.
    loader = UniqueKeyLoader(path.read_text(encoding="utf-8"))
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def iter_entries(value: object) -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from iter_entries(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_entries(item)


def load_contracts(root: Path) -> tuple[dict[Path, dict], Registry, list[str]]:
    documents = {}
    resources = []
    errors = []
    seen_ids = set()
    for path in sorted((root / "contracts").rglob("*.schema.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise ValueError("unsupported or missing JSON Schema dialect")
            uri = schema["$id"]
            if uri in seen_ids:
                raise ValueError(f"duplicate Schema $id: {uri}")
            seen_ids.add(uri)
            resource = Resource.from_contents(schema)
            resources.extend([(uri, resource), (path.resolve().as_uri(), resource)])
            documents[path.resolve()] = schema
        except Exception as exc:
            errors.append(f"invalid Schema {path.relative_to(root)}: {exc}")
    registry = Registry().with_resources(resources)
    for path, schema in documents.items():
        for key, ref in iter_entries(schema):
            if key == "$ref":
                try:
                    registry.resolver(schema["$id"]).lookup(ref)
                except Exception as exc:
                    errors.append(f"unresolved Schema ref in {path.name}: {ref}: {exc}")
    return documents, registry, errors


def json_pointer(document: object, ref: str) -> object:
    if not ref.startswith("#/"):
        raise ValueError(f"only local OpenAPI references are allowed: {ref}")
    result = document
    for part in unquote(ref[2:]).split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        result = result[int(key)] if isinstance(result, list) else result[key]
    return result


def load_openapi(root: Path) -> tuple[dict, list[str]]:
    try:
        spec = load_yaml(root / "contracts/openapi.yaml")
        for key, ref in iter_entries(spec):
            if key == "$ref":
                json_pointer(spec, ref)
        validate(spec)
        return spec, []
    except Exception as exc:
        return {}, [f"invalid OpenAPI: {exc}"]


def validator_for_contract(root: Path, target: str, documents: dict, registry: Registry, api: dict):
    relative, _, fragment = target.partition("#")
    if relative == "contracts/openapi.yaml":
        json_pointer(api, "#" + fragment)
        schema = {
            "$ref": "#" + fragment,
            "components": api["components"],
            "paths": api["paths"],
        }
        return Draft202012Validator(schema, format_checker=FormatChecker())
    path = (root / relative).resolve()
    schema = documents[path]
    if fragment:
        schema = {"$ref": schema["$id"] + "#" + fragment}
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def check_examples(root: Path, documents: dict, registry: Registry, api: dict) -> list[str]:
    errors = []
    try:
        manifest = load_yaml(root / "contracts/examples/manifest.yaml")
        fixtures = manifest["fixtures"]
        if not isinstance(fixtures, list) or not fixtures:
            raise ValueError("contract fixtures must not be empty")
        seen = set()
        for fixture in fixtures:
            if fixture["id"] in seen:
                raise ValueError(f"duplicate fixture: {fixture['id']}")
            seen.add(fixture["id"])
            validator = validator_for_contract(root, fixture["schema"], documents, registry, api)
            failures = list(validator.iter_errors(fixture["data"]))
            semantic_errors = product_execution_semantic_errors(fixture)
            expected = fixture["expected_valid"]
            if not isinstance(expected, bool):
                raise ValueError("expected_valid must be a boolean")
            actual_valid = not failures and not semantic_errors
            if actual_valid != expected:
                detail = (
                    failures[0].message
                    if failures
                    else semantic_errors[0]
                    if semantic_errors
                    else "invalid example was accepted"
                )
                errors.append(f"contract fixture {fixture['id']} failed: {detail}")
    except Exception as exc:
        errors.append(f"contract fixtures invalid: {exc}")
    return errors


def product_execution_semantic_errors(fixture: dict) -> list[str]:
    """Check cross-field invariants that JSON Schema cannot express."""
    if fixture.get("schema") != "contracts/schemas/product-review-execution.schema.json":
        return []
    payload = fixture["data"]
    errors = []
    coverage = payload["coverage"]
    if (
        coverage["status"] == "complete"
        and coverage["planned_units"] != coverage["completed_units"]
    ):
        errors.append("complete coverage count does not match planned units")
    authorized = set(payload["authorization"]["authorized_document_hashes"])
    for call in payload["model_calls"]:
        if call["state"] in {"dispatched", "succeeded", "failed", "unknown"}:
            if not set(call["document_hashes"]).issubset(authorized):
                errors.append("dispatched model call includes an unauthorized document hash")
                break
    return errors


def safe_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes repository: {relative}")
    return target


def check_dependencies(
    records: dict[str, dict],
    prefix: str,
    *,
    allow_in_progress_before_dependencies: bool = False,
) -> list[str]:
    errors = []
    visiting = set()
    visited = set()

    def visit(identifier):
        if identifier in visiting:
            errors.append(f"{prefix} dependency cycle at {identifier}")
            return
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in records[identifier]["depends_on"]:
            if dependency not in records:
                errors.append(f"{prefix} {identifier} has unknown dependency {dependency}")
            else:
                visit(dependency)
                dependency_incomplete = records[dependency]["status"] != "completed"
                unit_status = records[identifier]["status"]
                if dependency_incomplete and unit_status == "completed":
                    errors.append(f"{prefix} {identifier} completed before {dependency} completed")
                elif (
                    dependency_incomplete
                    and unit_status == "in_progress"
                    and not allow_in_progress_before_dependencies
                ):
                    errors.append(f"{prefix} {identifier} started before {dependency} completed")
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in records:
        visit(identifier)
    return errors


def check_tasks(root: Path, declared: set[str], schema: dict) -> tuple[dict, list[str]]:
    records = {}
    errors = []
    paths = sorted((root / "tasks/active").glob("TASK-*.yaml"))
    paths += sorted((root / "tasks/completed").glob("TASK-*.yaml"))
    if not paths:
        errors.append("no task files found")
    for path in paths:
        try:
            task = load_yaml(path)
            Draft202012Validator(schema).validate(task)
            identifier = task["task_id"]
            if identifier in records or not path.name.startswith(identifier + "-"):
                raise ValueError("duplicate task ID or mismatching filename")
            if (path.parent.name == "completed") != (task["status"] == "completed"):
                raise ValueError("task status does not match active/completed directory")
            unknown = set(task["related_requirements"] + task["related_acceptance"]) - declared
            if unknown:
                raise ValueError(f"unknown requirement IDs: {sorted(unknown)}")
            mandatory = {"AGENTS.md", "PROJECT_STATE.md", "docs/index.md"}
            if not mandatory.issubset(task["read_first"]):
                raise ValueError("read_first must include AGENTS, PROJECT_STATE and docs/index")
            for relative in task["read_first"]:
                if not safe_path(root, relative).is_file():
                    raise ValueError(f"read_first file missing: {relative}")
            local_checks = set()
            for check in task["acceptance_checks"]:
                if check["id"] in local_checks:
                    raise ValueError(f"duplicate local acceptance ID: {check['id']}")
                local_checks.add(check["id"])
                for evidence in check["evidence"]:
                    if not safe_path(root, evidence.split("::", 1)[0]).is_file():
                        raise ValueError(f"evidence file missing: {evidence}")
            for relative in task["allowed_paths"] + task["must_not_change"]:
                safe_path(root, relative)
            records[identifier] = task
        except Exception as exc:
            errors.append(f"invalid task {path.name}: {exc}")
    errors.extend(check_dependencies(records, "task"))
    return records, errors


def check_roadmap(root: Path, declared: set[str], tasks: dict) -> list[str]:
    try:
        roadmap = load_yaml(root / "docs/development/roadmap.yaml")
        milestones = roadmap["milestones"]
        if not milestones:
            raise ValueError("empty roadmap")
        records = {}
        covered_requirements = set()
        assigned_tasks = set()
        for milestone in milestones:
            if milestone["id"] in records:
                raise ValueError("duplicate milestone ID")
            if milestone["status"] not in {"planned", "in_progress", "completed"}:
                raise ValueError("invalid milestone status")
            if not milestone["deliverables"] or not milestone["exit_checks"]:
                raise ValueError("milestone missing deliverables/exit checks")
            for task_id in milestone["tasks"]:
                if task_id in assigned_tasks:
                    raise ValueError(f"task assigned to multiple milestones: {task_id}")
                assigned_tasks.add(task_id)
                if task_id not in tasks:
                    raise ValueError(f"milestone references unknown task {task_id}")
                if milestone["status"] == "completed" and tasks[task_id]["status"] != "completed":
                    raise ValueError("completed milestone has unfinished tasks")
            if set(milestone["related_requirements"] + milestone["related_acceptance"]) - declared:
                raise ValueError("milestone references unknown requirements")
            covered_requirements.update(
                milestone["related_requirements"] + milestone["related_acceptance"]
            )
            records[milestone["id"]] = milestone
        if declared - covered_requirements:
            raise ValueError(
                f"requirements without milestones: {sorted(declared - covered_requirements)}"
            )
        if set(tasks) - assigned_tasks:
            raise ValueError(f"tasks without milestones: {sorted(set(tasks) - assigned_tasks)}")
        errors = check_dependencies(records, "milestone")
        errors.extend(check_delivery_units(roadmap, tasks))
        return errors
    except Exception as exc:
        return [f"invalid roadmap: {exc}"]


def check_delivery_units(roadmap: dict, tasks: dict) -> list[str]:
    """Validate the adopted product plan's unit map and dependency graph."""
    try:
        units = roadmap["product_delivery_units"]
        if not isinstance(units, list) or not units:
            raise ValueError("empty product_delivery_units")
        records = {}
        for unit in units:
            identifier = unit["id"]
            if identifier in records:
                raise ValueError(f"duplicate delivery unit ID: {identifier}")
            if unit["status"] not in {"planned", "in_progress", "completed"}:
                raise ValueError(f"invalid delivery unit status: {identifier}")
            if not unit["tasks"]:
                raise ValueError(f"delivery unit has no task mapping: {identifier}")
            unknown_tasks = set(unit["tasks"]) - set(tasks)
            if unknown_tasks:
                raise ValueError(
                    f"delivery unit {identifier} references unknown tasks: {sorted(unknown_tasks)}"
                )
            unknown_decisions = set(unit.get("blocked_decisions", [])) - {
                "D1",
                "D2",
                "D3",
                "D4",
            }
            if unknown_decisions:
                raise ValueError(
                    f"delivery unit {identifier} references unknown decisions: "
                    f"{sorted(unknown_decisions)}"
                )
            records[identifier] = unit
        expected = {f"U{number:02}" for number in range(1, 17)}
        if set(records) != expected:
            raise ValueError(
                f"delivery unit IDs differ from U01-U16: "
                f"missing={sorted(expected - set(records))}, "
                f"unexpected={sorted(set(records) - expected)}"
            )
        # Unit dependencies gate completion. In-progress engineering can proceed on
        # independent work while a separate dependency remains open.
        return check_dependencies(
            records,
            "delivery unit",
            allow_in_progress_before_dependencies=True,
        )
    except Exception as exc:
        return [f"invalid product delivery units: {exc}"]


def check_product_traceability(root: Path, declared: set[str]) -> list[str]:
    """Require every declared FR/SEC/NFR/AC to map through a unit to its G3 record."""
    try:
        traceability = load_yaml(root / "docs/development/product-delivery-traceability.yaml")
        roadmap = load_yaml(root / "docs/development/roadmap.yaml")
        requirements = traceability["requirements"]
        evidence_records = traceability["evidence_records"]
        unit_ids = {unit["id"] for unit in roadmap["product_delivery_units"]}
        if set(requirements) != declared:
            raise ValueError(
                "traceability requirement IDs differ from declarations: "
                f"missing={sorted(declared - set(requirements))}, "
                f"unexpected={sorted(set(requirements) - declared)}"
            )
        if set(evidence_records) != unit_ids:
            raise ValueError(
                "traceability evidence records differ from delivery units: "
                f"missing={sorted(unit_ids - set(evidence_records))}, "
                f"unexpected={sorted(set(evidence_records) - unit_ids)}"
            )
        for requirement_id, mapped_units in requirements.items():
            if not isinstance(mapped_units, list) or not mapped_units:
                raise ValueError(f"requirement has no delivery unit: {requirement_id}")
            unknown_units = set(mapped_units) - unit_ids
            if unknown_units:
                raise ValueError(
                    f"requirement {requirement_id} references unknown units: "
                    f"{sorted(unknown_units)}"
                )
        for unit_id, reference in evidence_records.items():
            if not isinstance(reference, str) or not reference:
                raise ValueError(f"delivery unit has no evidence record: {unit_id}")
            relative = reference.split("#", maxsplit=1)[0]
            target = safe_path(root, relative)
            if not target.is_file():
                raise ValueError(f"delivery unit evidence record does not exist: {reference}")
        return []
    except Exception as exc:
        return [f"invalid product traceability map: {exc}"]


def check_secrets(root: Path) -> list[str]:
    errors = []
    suspicious = re.compile(
        r"(?im)[\"']?\b(api[_-]?key|access[_-]?token|secret[_-]?key)\b[\"']?\s*[:=]\s*"
        r"(?:[\"']([^\"'\r\n]+)[\"']|([^\s,#\r\n}]+))"
    )
    private_key = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
    if (root / ".git").exists():
        git_binary = shutil.which("git")
        if git_binary is None:
            return ["Git executable missing; tracked-secret verification cannot run"]
        index = subprocess.run(  # noqa: S603,S607 -- fixed read-only Git query, no shell
            [git_binary, "-C", str(root), "ls-files", "--cached", "-z"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if index.returncode:
            errors.append("cannot verify tracked secret files from Git index")
        else:
            for relative in index.stdout.decode("utf-8").split("\0"):
                path = Path(relative)
                if relative and (
                    path.name == ".env"
                    or (path.name.startswith(".env.") and path.name != ".env.example")
                    or set(path.parts) & {"secrets", ".venv", ".verification"}
                ):
                    errors.append(f"forbidden tracked secret/runtime file: {relative}")
    for folder, directories, files in root.walk():
        directories[:] = [name for name in directories if name not in IGNORED_DIRS]
        for name in files:
            path = folder / name
            if name == ".env" or name.startswith(".env.") and name != ".env.example":
                continue  # local, untracked credentials; tracked versions are blocked above
            if (
                path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".pem"}
                and name != ".env.example"
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            assignments = [
                match.group(2) or match.group(3) for match in suspicious.finditer(content)
            ]
            detected = any(
                len(value) >= 12 and not value.startswith(("change-me", "example", "configured"))
                for value in assignments
            )
            if private_key.search(content) or detected:
                errors.append(f"possible secret in source: {path.relative_to(root)}")
    return errors


def verify_repository(root: Path = ROOT) -> list[str]:
    errors = [f"missing required file: {p}" for p in REQUIRED_PATHS if not (root / p).is_file()]
    documents, registry, contract_errors = load_contracts(root)
    errors.extend(contract_errors)
    api, api_errors = load_openapi(root)
    errors.extend(api_errors)
    errors.extend(check_examples(root, documents, registry, api))
    ids = []
    for path in (root / "docs/requirements").glob("*.md"):
        ids.extend(
            re.findall(r"(?m)^\| ((?:FR|SEC|NFR|AC)-\d{3}) \|", path.read_text(encoding="utf-8"))
        )
    if len(ids) != len(set(ids)):
        errors.append("duplicate requirement declarations")
    declared = set(ids)
    errors.extend(check_product_traceability(root, declared))
    for prefix in ("FR", "SEC", "NFR", "AC"):
        if not any(item.startswith(prefix + "-") for item in declared):
            errors.append(f"no declared {prefix} requirements")
    task_schema = documents.get((root / "contracts/schemas/task.schema.json").resolve())
    if task_schema:
        try:
            Draft202012Validator(task_schema).validate(load_yaml(root / "tasks/template.yaml"))
        except Exception as exc:
            errors.append(f"invalid task template: {exc}")
        tasks, task_errors = check_tasks(root, declared, task_schema)
        errors.extend(task_errors)
        errors.extend(check_roadmap(root, declared, tasks))
    for folder in ("src", "tests", "scripts"):
        for path in (root / folder).rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"invalid Python {path.relative_to(root)}: {exc}")
    for path in (root / "docs/decisions").glob("ADR-*.md"):
        content = path.read_text(encoding="utf-8")
        if any(marker not in content for marker in ("状态：", "## 决策", "## 后果", "## 备选方案")):
            errors.append(f"incomplete ADR: {path.name}")
    try:
        if not check_state(root):
            errors.append("generated State differs from JSON Schema; run scripts/generate_state.py")
    except Exception as exc:
        errors.append(f"State generation check failed: {exc}")
    errors.extend(check_secrets(root))
    law_count = len(list((root / "knowledge/legal").rglob("*.txt")))
    if law_count < 40:
        errors.append(f"legal corpus incomplete: {law_count} text files (not an efficacy check)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    root = parser.parse_args().root.resolve()
    errors = verify_repository(root)
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    print("PASS: contracts, examples, generated State and scoped task evidence")
    print("Scope: development baseline only; business/security/release acceptance remains pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
