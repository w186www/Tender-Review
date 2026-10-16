"""Host-side, read-only proof that the public API still runs the offline mode.

The controlled DEC-007 round must not start while the public API could still reach a
supplier. The operator used to *declare* that with ``--online-api-offline-verified``; that
declaration is kept, but it is no longer sufficient: the entry point also requires a fresh
evidence file produced by this script on the host.

What this script does
---------------------
It inspects the running deployment with read-only Docker commands -- ``docker compose ...
ps``, ``docker ps`` and ``docker inspect`` -- and writes one JSON evidence document:

* when the check ran and which compose project/container it describes,
* the api container's name, full id, image reference and image id,
* the api container's **effective** ``DEPLOY_REVIEW_MODE`` (read from the container's own
  environment in ``docker inspect``, not from the compose file),
* its entrypoint, command, state/running flag and health status,
* whether a second execution instance (another container whose effective
  ``DEPLOY_REVIEW_MODE`` is ``authorized-real``) is running,
* the verdict: ``ok``, ``untrusted`` or ``unknown``.

What it never does
------------------
No container is created, started, stopped, removed or entered; no Docker socket is mounted
anywhere and no container ever receives Docker access; nothing is written except the
evidence JSON under ``--evidence-dir``. The container environment is *iterated* only to
extract the two whitelisted, non-secret values (``DEPLOY_REVIEW_MODE``, ``APP_ENV``):
everything else is discarded in the same loop and can never reach the evidence file, the
standard output or a log, so no credential and no full environment list is ever emitted.

Verdicts and exit codes
-----------------------
``ok`` (exit 0)         mode is ``offline``, the api container runs, image/entrypoint are
                        the expected ones and no second authorized-real instance runs.
``untrusted`` (exit 3)  a definite contradiction: the api serves ``authorized-real``, is not
                        running, does not run the expected image/entrypoint, or another
                        container runs in ``authorized-real`` mode.
``unknown`` (exit 2)    the mode cannot be established at all (missing container, failed
                        ``docker inspect``, absent ``DEPLOY_REVIEW_MODE``). Stop immediately;
                        do not launch supplier calls.

Both non-``ok`` verdicts are fail-closed and the evidence file is written either way, so the
refusal is auditable. ``--fixture-dir`` replays canned command output (``compose-ps.json``,
``docker-ps.json``, ``inspect-<container-id>.json``) and exists for tests and offline
reviews of this script only; the recorded ``docker_binary`` then reads ``fixture:<dir>``.

The evidence is *content*, not a signature: the preflight validates its verdict, its
freshness and its identifiers against the current deployment, and the operator who runs
this script on the host stays trusted. It does prove that a check actually ran against the
container it names, which the bare operator flag never did.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = "v1alpha1"
SCRIPT_NAME = "deploy/verify_api_offline_mode.sh"

VERDICT_OK = "ok"
VERDICT_UNTRUSTED = "untrusted"
VERDICT_UNKNOWN = "unknown"
EXIT_CODE: dict[str, int] = {VERDICT_OK: 0, VERDICT_UNTRUSTED: 3, VERDICT_UNKNOWN: 2}

OFFLINE_MODE = "offline"
AUTHORIZED_REAL_MODE = "authorized-real"
EXPECTED_COMPOSE_SERVICE = "api"
# docker-compose.demo.yml: api service command `["python", "deploy/api_entry.py"]` and a
# deployment image without an ENTRYPOINT of its own.
EXPECTED_API_COMMAND = ("python", "deploy/api_entry.py")
EXPECTED_API_ENTRYPOINT: tuple[str, ...] = ()
API_IMAGE_PREFIX = "tender-review-api"
MODE_VARIABLE = "DEPLOY_REVIEW_MODE"
APP_ENV_VARIABLE = "APP_ENV"
HEALTH_ABSENT = "none"

# The only environment values this script may ever read, record or print. Everything else in
# the container environment is dropped while iterating and never leaves that loop.
ENVIRONMENT_WHITELIST = (MODE_VARIABLE, APP_ENV_VARIABLE)

# The evidence document's key whitelist: a dump of any other value cannot even be stored.
EVIDENCE_KEYS = (
    "schema_version",
    "script",
    "docker_binary",
    "checked_at",
    "compose_project",
    "compose_file",
    "api",
    "execution_instances",
    "checks",
    "failures",
    "verdict",
)
API_KEYS = (
    "service",
    "container_name",
    "container_id",
    "image_reference",
    "image_id",
    "deploy_review_mode",
    "app_env",
    "entrypoint",
    "command",
    "state",
    "running",
    "health_status",
)
EXECUTION_KEYS = ("scanned_container_count", "authorized_real_instances")
CHECK_KEYS = (
    "review_mode_offline",
    "container_running",
    "health_acceptable",
    "image_expected",
    "entrypoint_expected",
    "no_second_authorized_real_instance",
)

MAX_EVIDENCE_BYTES = 1_000_000
# ``datetime.UTC`` only exists from Python 3.11; this script must also run on the
# distribution python3.10 of the target host, so the long-standing alias stays.
UTC = timezone.utc  # noqa: UP017 - python 3.10 hosts
CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")
DEFAULT_COMPOSE_FILE = "docker-compose.demo.yml"
DEFAULT_ENV_FILE = "deploy/.env"
DEFAULT_EVIDENCE_DIR = Path("/opt/tender-review-private/evidence")
DEFAULT_IMAGE_TAG = "demo"
COMMAND_TIMEOUT_SECONDS = 60


class EvidenceRejected(RuntimeError):
    """The evidence file cannot be trusted for a paid round."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class DockerRunner(Protocol):
    """The one seam through which every Docker invocation goes (injectable in tests)."""

    def __call__(self, args: Sequence[str]) -> CommandResult: ...


def subprocess_runner(binary: str) -> DockerRunner:
    """Run the real Docker CLI with an explicit argument list and no shell."""

    def run(args: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv list, shell not used
                [binary, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CommandResult(125, "", f"{type(exc).__name__}")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    return run


def fixture_runner(directory: Path) -> DockerRunner:
    """Replay canned command output; tests and offline reviews of this script only."""

    def run(args: Sequence[str]) -> CommandResult:
        name = fixture_name(args)
        path = directory / name
        if not path.is_file():
            return CommandResult(1, "", f"fixture {name} is absent")
        return CommandResult(0, path.read_text(encoding="utf-8"), "")

    return run


def fixture_name(args: Sequence[str]) -> str:
    """The documented fixture file name of one invocation."""
    if args and args[0] == "compose":
        return "compose-ps.json"
    if len(args) >= 2 and args[0] == "ps":
        return "docker-ps.json"
    if len(args) >= 2 and args[0] == "inspect":
        return f"inspect-{args[-1]}.json"
    return "unsupported.json"


def is_read_only(args: Sequence[str]) -> bool:
    """Every invocation must be a read-only listing or inspection."""
    if not args:
        return False
    if args[0] == "compose":
        return "ps" in args
    return args[0] in {"ps", "inspect"}


# --------------------------------------------------------------------------- parsing
def json_objects(text: str) -> list[dict[str, Any]]:
    """Accept both the NDJSON (compose) and the JSON-array (inspect) shapes."""
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        loaded = json.loads(stripped)
        return [item for item in loaded if isinstance(item, dict)]
    objects = []
    for line in stripped.splitlines():
        line = line.strip()
        if line:
            item = json.loads(line)
            if isinstance(item, dict):
                objects.append(item)
    return objects


def choose_api_entry(entries: Sequence[Mapping[str, Any]], service: str) -> dict[str, Any] | None:
    """The compose service container (never a ``run`` one-off) of the given service."""

    def rank(entry: Mapping[str, Any]) -> tuple[int, int, int, str]:
        name = str(entry.get("Name", ""))
        numbered = bool(re.search(rf"-{re.escape(service)}-\d+$", name))
        running = str(entry.get("State", "")).lower() == "running"
        return (
            0 if numbered and running else 1,
            0 if numbered else 1,
            0 if running else 1,
            name,
        )

    candidates = [dict(entry) for entry in entries if str(entry.get("Service", "")) == service]
    if not candidates:
        return None
    return min(candidates, key=rank)


def whitelisted_environment(config_environment: Sequence[str] | None) -> dict[str, str]:
    """Only the whitelisted values survive; every other variable is dropped in the loop."""
    values: dict[str, str] = {}
    for item in config_environment or []:
        name, _, value = str(item).partition("=")
        if name in ENVIRONMENT_WHITELIST:
            values[name] = value
    return values


def container_facts(document: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Whitelisted facts of one inspected container plus the fields that could not be read."""
    missing: list[str] = []
    config = document.get("Config") or {}
    state = document.get("State") or {}
    environment = whitelisted_environment(config.get("Env"))
    values: dict[str, Any] = {
        "container_id": document.get("Id"),
        "container_name": str(document.get("Name", "")).lstrip("/"),
        "image_reference": config.get("Image"),
        "image_id": document.get("Image"),
        "state": state.get("Status"),
        "running": bool(state.get("Running")),
        "health_status": (state.get("Health") or {}).get("Status", HEALTH_ABSENT),
        "entrypoint": [str(item) for item in (config.get("Entrypoint") or [])],
        "command": [str(item) for item in (config.get("Cmd") or [])],
        "deploy_review_mode": environment.get(MODE_VARIABLE),
        "app_env": environment.get(APP_ENV_VARIABLE, ""),
    }
    for field in ("container_id", "container_name", "image_reference", "image_id", "state"):
        if not values[field]:
            missing.append(field)
    if values["deploy_review_mode"] is None:
        missing.append(MODE_VARIABLE)
    return values, missing


def image_tag_from_env_file(path: Path) -> str:
    """``IMAGE_TAG`` from the deployment env file; never a secret, never exported."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_IMAGE_TAG
    for line in text.splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name.strip() == "IMAGE_TAG" and value.strip():
            return value.strip()
    return DEFAULT_IMAGE_TAG


def expected_image_reference(env_file: Path, override: str | None) -> str:
    if override:
        return override
    return f"{API_IMAGE_PREFIX}:{image_tag_from_env_file(env_file)}"


# --------------------------------------------------------------------------- inspection
def inspect_deployment(
    *,
    runner: DockerRunner,
    docker_binary: str,
    compose_file: str,
    env_file: str,
    expected_service: str,
    expected_image: str,
    checked_at: datetime,
    compose_path: Path,
) -> dict[str, Any]:
    """Read-only inspection of the api container and of every other container on the host."""
    unknown: list[str] = []
    failures: list[str] = []
    compose_result = runner(
        [
            "compose",
            "--env-file",
            env_file,
            "-f",
            compose_file,
            "ps",
            "--all",
            "--no-trunc",
            "--format",
            "json",
        ]
    )
    if compose_result.returncode != 0:
        unknown.append("docker compose ps failed")
        entries: list[dict[str, Any]] = []
    else:
        try:
            entries = json_objects(compose_result.stdout)
        except ValueError:
            unknown.append("docker compose ps did not return JSON")
            entries = []
    api_entry = choose_api_entry(entries, expected_service)
    project = ""
    if api_entry is not None:
        project = str(api_entry.get("Project", ""))

    first_result = runner(["ps", "-aq", "--no-trunc"])
    if first_result.returncode != 0:
        unknown.append("docker ps failed")
        host_ids: list[str] = []
    else:
        host_ids = [line.strip() for line in first_result.stdout.splitlines() if line.strip()]

    candidates: list[tuple[str, Mapping[str, Any] | None]] = []
    seen: set[str] = set()
    for entry in entries:
        container_id = str(entry.get("ID", "")).strip()
        if container_id and container_id not in seen:
            seen.add(container_id)
            candidates.append((container_id, entry))
    for container_id in host_ids:
        if container_id not in seen:
            seen.add(container_id)
            candidates.append((container_id, None))

    api_facts: dict[str, Any] = {}
    inspected: list[tuple[str, Mapping[str, Any] | None, dict[str, Any], list[str]]] = []
    for container_id, entry in candidates:
        result = runner(["inspect", "--type", "container", container_id])
        if result.returncode != 0:
            if api_entry is not None and str(api_entry.get("ID", "")).strip() == container_id:
                unknown.append(f"docker inspect failed for the api container {container_id}")
            continue
        try:
            documents = json_objects(result.stdout)
        except ValueError:
            if api_entry is not None and str(api_entry.get("ID", "")).strip() == container_id:
                unknown.append(f"docker inspect returned no JSON for {container_id}")
            continue
        if not documents:
            continue
        facts, missing = container_facts(documents[0])
        inspected.append((container_id, entry, facts, missing))
        if api_entry is not None and str(api_entry.get("ID", "")).strip() == container_id:
            api_facts = facts
            if missing:
                unknown.append(
                    "the api container environment/state is missing: "
                    + ", ".join(sorted(missing))
                )

    if api_entry is None:
        unknown.append(
            f"no running container of the compose service {expected_service!r} was found"
        )
    elif not api_facts:
        unknown.append("the api container could not be inspected")

    second_instances: list[dict[str, str]] = []
    for container_id, _entry, facts, _missing in inspected:
        if facts.get("deploy_review_mode") != AUTHORIZED_REAL_MODE:
            continue
        if not facts.get("running"):
            continue
        if api_facts and facts.get("container_id") == api_facts.get("container_id"):
            continue
        second_instances.append(
            {"container_name": str(facts.get("container_name", "")), "container_id": container_id}
        )

    checks = {
        "review_mode_offline": api_facts.get("deploy_review_mode") == OFFLINE_MODE,
        "container_running": bool(api_facts.get("running")),
        # The rule is "healthy, or at least running": a container without a healthcheck
        # (the api service declares none) is acceptable while it runs.
        "health_acceptable": bool(api_facts.get("running")),
        "image_expected": api_facts.get("image_reference") == expected_image,
        "entrypoint_expected": (
            tuple(api_facts.get("entrypoint") or []) == EXPECTED_API_ENTRYPOINT
            and tuple(api_facts.get("command") or []) == EXPECTED_API_COMMAND
        ),
        "no_second_authorized_real_instance": not second_instances,
    }
    if api_facts:
        mode = api_facts.get("deploy_review_mode")
        if mode is None:
            unknown.append("the api container does not define the effective review mode")
        elif mode != OFFLINE_MODE:
            failures.append(
                f"the api container's effective {MODE_VARIABLE} is {mode!r}, not {OFFLINE_MODE!r}"
            )
        if not api_facts.get("running"):
            failures.append("the api container is not running")
        if api_facts.get("image_reference") != expected_image:
            failures.append(
                f"the api container image is {api_facts.get('image_reference')!r}, "
                f"expected {expected_image!r}"
            )
        if not checks["entrypoint_expected"]:
            failures.append(
                "the api container entrypoint/command is not the deployment entrypoint "
                f"(entrypoint={api_facts.get('entrypoint')!r}, "
                f"command={api_facts.get('command')!r})"
            )
    for instance in second_instances:
        failures.append(
            "another container runs in authorized-real mode: "
            f"{instance['container_name']} ({instance['container_id']})"
        )

    verdict = VERDICT_OK
    if unknown:
        verdict = VERDICT_UNKNOWN
    elif failures:
        verdict = VERDICT_UNTRUSTED

    api_payload = {
        "service": expected_service,
        "container_name": str(api_facts.get("container_name", "")),
        "container_id": str(api_facts.get("container_id", "")),
        "image_reference": str(api_facts.get("image_reference", "")),
        "image_id": str(api_facts.get("image_id", "")),
        "deploy_review_mode": str(api_facts.get("deploy_review_mode") or ""),
        "app_env": str(api_facts.get("app_env", "")),
        "entrypoint": [str(item) for item in (api_facts.get("entrypoint") or [])],
        "command": [str(item) for item in (api_facts.get("command") or [])],
        "state": str(api_facts.get("state", "")),
        "running": bool(api_facts.get("running")),
        "health_status": str(api_facts.get("health_status", HEALTH_ABSENT)),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "script": SCRIPT_NAME,
        "docker_binary": docker_binary,
        "checked_at": checked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "compose_project": project,
        "compose_file": str(compose_path),
        "api": api_payload,
        "execution_instances": {
            "scanned_container_count": len(inspected),
            "authorized_real_instances": second_instances,
        },
        "checks": checks,
        "failures": [*unknown, *failures],
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- consumer side
@dataclass(frozen=True, slots=True)
class HostOfflineEvidence:
    """The accepted host evidence, reduced to the fields a preflight may look at."""

    path: str
    checked_at: str
    age_seconds: float
    max_age_seconds: int
    compose_project: str
    api_container_id: str
    api_container_name: str
    api_image_reference: str
    api_image_id: str
    entrypoint: tuple[str, ...]
    command: tuple[str, ...]
    deploy_review_mode: str
    docker_binary: str
    health_status: str
    second_authorized_real_instances: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "checked_at": self.checked_at,
            "age_seconds": round(self.age_seconds, 3),
            "max_age_seconds": self.max_age_seconds,
            "compose_project": self.compose_project,
            "api_container_id": self.api_container_id,
            "api_container_name": self.api_container_name,
            "api_image_reference": self.api_image_reference,
            "api_image_id": self.api_image_id,
            "entrypoint": list(self.entrypoint),
            "command": list(self.command),
            "deploy_review_mode": self.deploy_review_mode,
            "docker_binary": self.docker_binary,
            "health_status": self.health_status,
            "second_authorized_real_instances": list(self.second_authorized_real_instances),
        }


def parse_checked_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise EvidenceRejected("the evidence has no checked_at timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EvidenceRejected("the evidence checked_at timestamp is not ISO 8601") from exc
    if parsed.tzinfo is None:
        raise EvidenceRejected("the evidence checked_at timestamp has no timezone")
    return parsed


def container_id_matches(evidence_id: str, current_id: str) -> bool:
    """Exact match, or an abbreviation that is at least 12 characters long."""
    if evidence_id == current_id:
        return True
    short, long = sorted((evidence_id, current_id), key=len)
    return len(short) >= 12 and long.startswith(short)


def require_whitelist(container: Mapping[str, Any], keys: Sequence[str], what: str) -> None:
    unexpected = sorted(set(container) - set(keys))
    if unexpected:
        raise EvidenceRejected(f"the evidence {what} holds unexpected fields: {unexpected}")
    absent = sorted(set(keys) - set(container))
    if absent:
        raise EvidenceRejected(f"the evidence {what} is missing fields: {absent}")


def load_evidence(
    path: Path | str,
    *,
    max_age_seconds: int,
    expected_api_container_id: str,
    expected_compose_project: str,
    now: datetime | None = None,
) -> HostOfflineEvidence:
    """Accept a fresh, ``ok`` evidence document describing the current deployment.

    Every rejection is fail-closed and names its reason; nothing here can be relaxed by an
    environment variable or a command line option of the caller.
    """
    if max_age_seconds < 60 or max_age_seconds > 3600:
        raise EvidenceRejected("the evidence freshness window must be 60..3600 seconds")
    if not str(path).strip():
        raise EvidenceRejected(
            "no host offline evidence was given; run deploy/verify_api_offline_mode.sh on the "
            "host and pass --host-offline-evidence <path>"
        )
    resolved = Path(path)
    if not resolved.is_file():
        raise EvidenceRejected(
            f"the host offline evidence is absent at {resolved}; run "
            "deploy/verify_api_offline_mode.sh on the host first"
        )
    if not expected_api_container_id.strip():
        raise EvidenceRejected(
            "the current api container id is required (DEC007_API_CONTAINER_ID or "
            "--api-container-id) so the evidence can be compared with the running deployment"
        )
    if not expected_compose_project.strip():
        raise EvidenceRejected(
            "the current compose project is required (DEPLOY_COMPOSE_PROJECT or "
            "--compose-project) so the evidence can be compared with the running deployment"
        )
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise EvidenceRejected(f"the host offline evidence is unreadable at {resolved}") from exc
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise EvidenceRejected("the host offline evidence exceeds the size limit")
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EvidenceRejected("the host offline evidence is not a JSON document") from exc
    if not isinstance(payload, dict):
        raise EvidenceRejected("the host offline evidence is not a JSON object")
    require_whitelist(payload, EVIDENCE_KEYS, "document")
    api = payload["api"]
    execution = payload["execution_instances"]
    if not isinstance(api, dict) or not isinstance(execution, dict):
        raise EvidenceRejected("the evidence api/execution_instances sections are not objects")
    require_whitelist(api, API_KEYS, "api section")
    require_whitelist(execution, EXECUTION_KEYS, "execution_instances section")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise EvidenceRejected(
            f"the evidence schema_version is {payload['schema_version']!r}, "
            f"expected {SCHEMA_VERSION!r}"
        )
    verdict = payload["verdict"]
    if verdict != VERDICT_OK:
        raise EvidenceRejected(
            f"the host evidence verdict is {verdict!r}; stop immediately and do not launch "
            "supplier calls"
        )
    if api["deploy_review_mode"] != OFFLINE_MODE:
        raise EvidenceRejected(
            f"the evidence reports the api container mode {api['deploy_review_mode']!r}, "
            f"expected {OFFLINE_MODE!r}"
        )
    if api["running"] is not True:
        raise EvidenceRejected("the evidence reports the api container is not running")
    instances = execution["authorized_real_instances"]
    if not isinstance(instances, list) or instances:
        raise EvidenceRejected("the evidence reports another authorized-real instance")
    checked_at = parse_checked_at(payload["checked_at"])
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    age = (moment - checked_at).total_seconds()
    if age < -60:
        raise EvidenceRejected("the evidence checked_at timestamp lies in the future")
    if age > max_age_seconds:
        raise EvidenceRejected(
            f"the evidence is {age:.0f}s old and the freshness window is {max_age_seconds}s; "
            "run deploy/verify_api_offline_mode.sh again"
        )
    evidence_id = str(api["container_id"]).strip().lower()
    if not CONTAINER_ID.fullmatch(evidence_id):
        raise EvidenceRejected("the evidence api container id is not a container id")
    if not container_id_matches(evidence_id, expected_api_container_id.strip().lower()):
        raise EvidenceRejected(
            "the evidence describes a different api container than the current deployment"
        )
    project = str(payload["compose_project"]).strip()
    if not project:
        raise EvidenceRejected("the evidence has no compose project")
    if project != expected_compose_project.strip():
        raise EvidenceRejected(
            "the evidence describes a different compose project than the current deployment"
        )
    return HostOfflineEvidence(
        path=str(resolved),
        checked_at=str(payload["checked_at"]),
        age_seconds=age,
        max_age_seconds=max_age_seconds,
        compose_project=project,
        api_container_id=evidence_id,
        api_container_name=str(api["container_name"]),
        api_image_reference=str(api["image_reference"]),
        api_image_id=str(api["image_id"]),
        entrypoint=tuple(str(item) for item in api["entrypoint"]),
        command=tuple(str(item) for item in api["command"]),
        deploy_review_mode=str(api["deploy_review_mode"]),
        docker_binary=str(payload["docker_binary"]),
        health_status=str(api["health_status"]),
        second_authorized_real_instances=tuple(
            str(item) for item in execution["authorized_real_instances"]
        ),
    )


# --------------------------------------------------------------------------- entry point
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--docker-bin", default="docker", help="docker CLI to run (read-only)")
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="replay canned command output instead of Docker (tests/offline review only)",
    )
    parser.add_argument(
        "--compose-file", default=DEFAULT_COMPOSE_FILE, help="compose file of the deployment"
    )
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="deployment env file")
    parser.add_argument("--service", default=EXPECTED_COMPOSE_SERVICE, help="compose service")
    parser.add_argument(
        "--expected-image-ref",
        default=None,
        help="expected api image reference (default tender-review-api:<IMAGE_TAG>)",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
        help="directory the evidence JSON is written to",
    )
    parser.add_argument("--json", action="store_true", help="also print the evidence document")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: DockerRunner | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    moment = (now or (lambda: datetime.now(UTC)))()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    compose_path = Path(args.compose_file)
    env_file = Path(args.env_file)
    if runner is None:
        runner = (
            fixture_runner(args.fixture_dir)
            if args.fixture_dir is not None
            else subprocess_runner(args.docker_bin)
        )
    docker_binary = (
        f"fixture:{args.fixture_dir}" if args.fixture_dir is not None else args.docker_bin
    )
    evidence = inspect_deployment(
        runner=runner,
        docker_binary=docker_binary,
        compose_file=str(args.compose_file),
        env_file=str(args.env_file),
        expected_service=str(args.service),
        expected_image=expected_image_reference(env_file, args.expected_image_ref),
        checked_at=moment,
        compose_path=compose_path,
    )
    verdict = str(evidence["verdict"])
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    destination = evidence_dir / f"api-offline-{moment.strftime('%Y%m%dT%H%M%SZ')}.json"
    destination.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"evidence: {destination}")
    print(f"verdict: {verdict}")
    api = evidence["api"]
    print(
        "api container: "
        f"{api['container_name']} ({api['container_id']}) "
        f"mode={api['deploy_review_mode']} state={api['state']} "
        f"image={api['image_reference']} health={api['health_status']}"
    )
    for failure in evidence["failures"]:
        print(f"  - {failure}")
    if args.json:
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    if verdict == VERDICT_OK:
        print(
            "PASS: the public API runs in offline mode and no second authorized-real "
            "instance runs."
        )
    elif verdict == VERDICT_UNKNOWN:
        print(
            "STOP: the review mode could not be established. Stop immediately; do not launch "
            "supplier calls.",
            file=sys.stderr,
        )
    else:
        print(
            "STOP: the deployment contradicts the offline precondition. Stop immediately; do not "
            "launch supplier calls.",
            file=sys.stderr,
        )
    return EXIT_CODE[verdict]


if __name__ == "__main__":
    raise SystemExit(main())
