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
* whether a second real-model execution instance is running,
* the verdict: ``ok``, ``untrusted`` or ``unknown``.

Second-instance detection does not rely on the effective ``DEPLOY_REVIEW_MODE`` alone. The
isolated validation container started by ``scripts/task0027_real_ai_validation_app.py`` may
still declare ``DEPLOY_REVIEW_MODE=offline`` (its ceilings live in its own code), so the
actual start command and the image reference are inspected as well. Every running container
on the host other than the expected api container counts as a real-model execution instance
when any of these holds:

* its effective ``DEPLOY_REVIEW_MODE`` is ``authorized-real``,
* its entrypoint/command runs ``task0023_real_ai_app`` (the authorized-real assembly),
* its entrypoint/command runs ``task0027_real_ai_validation_app`` (the isolated entry),
* its entrypoint/command is ``deploy/api_entry.py`` and its ``DEPLOY_REVIEW_MODE`` is
  ``authorized-real``,
* its image reference carries the validation image tag (``task0027-validation``).

When the execution identity of a running container cannot be read at all (failed ``docker
inspect``, missing container id/image/command, unreadable running state, or the deployment
entry without a readable mode), the verdict is ``unknown``: this script never claims "no
second real-model instance exists" on incomplete information. A container that is
demonstrably not running is out of scope -- it cannot place a supplier call.

The evidence document is versioned (``SCHEMA_VERSION``); the preflight accepts exactly this
version, so an evidence file written by an older release of this script is rejected instead
of being read with a different meaning.

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
                        the expected ones and no second real-model execution instance runs.
``untrusted`` (exit 3)  a definite contradiction: the api serves ``authorized-real``, is not
                        running, does not run the expected image/entrypoint, or another
                        running container is a real-model execution instance (see above).
``unknown`` (exit 2)    the mode cannot be established at all (missing container, failed
                        ``docker inspect``, absent ``DEPLOY_REVIEW_MODE``) or the execution
                        identity of a running container could not be read. Stop immediately;
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

# v1alpha2: second-instance detection covers the start command and the image reference
# (``execution_instances.second_real_model_instances``, per-instance ``reason``), adds the
# ``all_running_containers_identified`` check, and fails closed as ``unknown`` when a running
# container's execution identity cannot be read.
SCHEMA_VERSION = "v1alpha2"
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

# Second-instance detection beyond the effective DEPLOY_REVIEW_MODE. The isolated validation
# container of scripts/task0027_real_ai_validation_app.py may run with
# DEPLOY_REVIEW_MODE=offline, so the start command and the image reference are checked too.
# The assembly tokens are matched as substrings, which covers both the ``<name>.py`` script
# form and the ``<name>:app`` module form of a uvicorn command.
AUTHORIZED_REAL_ASSEMBLY_MODULE = "task0023_real_ai_app"
VALIDATION_ENTRY_MODULE = "task0027_real_ai_validation_app"
DEPLOYMENT_ENTRY_SCRIPT = "api_entry.py"
VALIDATION_IMAGE_TAG = "task0027-validation"

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
EXECUTION_KEYS = ("scanned_container_count", "second_real_model_instances")
CHECK_KEYS = (
    "review_mode_offline",
    "container_running",
    "health_acceptable",
    "image_expected",
    "entrypoint_expected",
    "all_running_containers_identified",
    "no_second_real_model_instance",
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
    running = state.get("Running")
    values: dict[str, Any] = {
        "container_id": document.get("Id"),
        "container_name": str(document.get("Name", "")).lstrip("/"),
        "image_reference": config.get("Image"),
        "image_id": document.get("Image"),
        "state": state.get("Status"),
        # ``None`` means the flag itself could not be read: the container's running state is
        # then unknown and must be reported as such, never silently treated as "stopped".
        "running": running if isinstance(running, bool) else None,
        "health_status": (state.get("Health") or {}).get("Status", HEALTH_ABSENT),
        "entrypoint": [str(item) for item in (config.get("Entrypoint") or [])],
        "command": [str(item) for item in (config.get("Cmd") or [])],
        "deploy_review_mode": environment.get(MODE_VARIABLE),
        "app_env": environment.get(APP_ENV_VARIABLE, ""),
    }
    for field in ("container_id", "container_name", "image_reference", "image_id", "state"):
        if not values[field]:
            missing.append(field)
    if values["running"] is None:
        missing.append("running")
    if values["deploy_review_mode"] is None:
        missing.append(MODE_VARIABLE)
    return values, missing


def command_line(facts: Mapping[str, Any]) -> str:
    """The container's entrypoint and main process joined for rule matching."""
    parts = [*(facts.get("entrypoint") or []), *(facts.get("command") or [])]
    return " ".join(str(part) for part in parts)


def real_model_instance_reason(facts: Mapping[str, Any]) -> str | None:
    """Why this container is a real-model execution instance (``None`` if it is not one).

    The effective ``DEPLOY_REVIEW_MODE`` is the historical rule, but it misses the isolated
    validation container, which may declare ``offline`` while its command runs
    ``scripts/task0027_real_ai_validation_app.py``. The actual start command and the image
    reference are therefore checked as well.
    """
    mode = facts.get("deploy_review_mode")
    text = command_line(facts)
    image = str(facts.get("image_reference") or "")
    if AUTHORIZED_REAL_ASSEMBLY_MODULE in text:
        return (
            "the start command runs the authorized-real assembly "
            f"({AUTHORIZED_REAL_ASSEMBLY_MODULE})"
        )
    if VALIDATION_ENTRY_MODULE in text:
        return f"the start command runs the isolated validation entry ({VALIDATION_ENTRY_MODULE})"
    if DEPLOYMENT_ENTRY_SCRIPT in text and mode == AUTHORIZED_REAL_MODE:
        return (
            f"the start command runs {DEPLOYMENT_ENTRY_SCRIPT} with "
            f"{MODE_VARIABLE}={AUTHORIZED_REAL_MODE}"
        )
    if VALIDATION_IMAGE_TAG in image:
        return f"the image reference carries the validation image tag ({VALIDATION_IMAGE_TAG})"
    if mode == AUTHORIZED_REAL_MODE:
        return f"the effective {MODE_VARIABLE} is {AUTHORIZED_REAL_MODE}"
    return None


def identity_gap(facts: Mapping[str, Any]) -> str | None:
    """Why the execution identity of a container cannot be read (``None`` = it was read).

    A container that is demonstrably not running is out of scope: it cannot place a supplier
    call. Everything else fails closed. Whenever this returns a reason, the caller reports
    ``unknown`` -- it may never conclude that no second real-model instance exists.
    """
    running = facts.get("running")
    if running is False:
        return None
    if running is not True:
        return "the running state could not be read"
    missing = [
        name
        for name, readable in (
            ("container id", bool(str(facts.get("container_id") or "").strip())),
            ("image reference", bool(str(facts.get("image_reference") or "").strip())),
            ("entrypoint/command", bool(facts.get("entrypoint") or facts.get("command"))),
        )
        if not readable
    ]
    if missing:
        return f"the {', '.join(missing)} could not be read"
    if DEPLOYMENT_ENTRY_SCRIPT in command_line(facts) and facts.get("deploy_review_mode") is None:
        return f"the start command is the deployment entry but {MODE_VARIABLE} could not be read"
    return None


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
    # Every container whose execution identity could not be read. It drives the
    # ``all_running_containers_identified`` check: as long as one container is unreadable this
    # script may not claim that no second real-model instance exists.
    unidentified: list[str] = []
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
        unidentified.append("docker compose ps failed")
        entries: list[dict[str, Any]] = []
    else:
        try:
            entries = json_objects(compose_result.stdout)
        except ValueError:
            unknown.append("docker compose ps did not return JSON")
            unidentified.append("docker compose ps did not return JSON")
            entries = []
    api_entry = choose_api_entry(entries, expected_service)
    project = ""
    if api_entry is not None:
        project = str(api_entry.get("Project", ""))

    first_result = runner(["ps", "-aq", "--no-trunc"])
    if first_result.returncode != 0:
        unknown.append("docker ps failed")
        # The namespace of host containers itself could not be enumerated.
        unidentified.append("docker ps failed")
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
    for container_id, compose_record in candidates:
        result = runner(["inspect", "--type", "container", container_id])
        if result.returncode != 0:
            reason = (
                f"docker inspect failed for the container {container_id}; its execution "
                "identity could not be read"
            )
            unknown.append(reason)
            unidentified.append(reason)
            continue
        try:
            documents = json_objects(result.stdout)
        except ValueError:
            reason = (
                f"docker inspect returned no JSON for the container {container_id}; its "
                "execution identity could not be read"
            )
            unknown.append(reason)
            unidentified.append(reason)
            continue
        if not documents:
            reason = (
                f"docker inspect returned no document for the container {container_id}; its "
                "execution identity could not be read"
            )
            unknown.append(reason)
            unidentified.append(reason)
            continue
        facts, missing = container_facts(documents[0])
        inspected.append((container_id, compose_record, facts, missing))
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

    # The expected api container is excluded by container id: it is the deployment that must
    # stay offline, not a "second" instance. Both the id docker reported for the api service
    # and the id read from its own inspection are excluded.
    excluded_ids = {
        str(value).strip()
        for value in (
            (api_entry or {}).get("ID", ""),
            api_facts.get("container_id", ""),
        )
        if str(value).strip()
    }
    second_instances: list[dict[str, str]] = []
    for container_id, _entry, facts, _missing in inspected:
        if container_id in excluded_ids or str(facts.get("container_id") or "") in excluded_ids:
            continue
        gap = identity_gap(facts)
        if gap is not None:
            name = str(facts.get("container_name") or container_id)
            unidentified.append(f"{name} ({container_id})")
            unknown.append(
                f"the execution identity of a running container could not be read: {name} "
                f"({container_id}): {gap}"
            )
            continue
        if facts.get("running") is not True:
            continue
        instance_reason = real_model_instance_reason(facts)
        if instance_reason:
            second_instances.append(
                {
                    "container_name": str(facts.get("container_name", "")),
                    "container_id": container_id,
                    "reason": instance_reason,
                }
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
        "all_running_containers_identified": not unidentified,
        "no_second_real_model_instance": not second_instances,
    }
    if api_facts:
        mode = api_facts.get("deploy_review_mode")
        if mode is None:
            unknown.append("the api container does not define the effective review mode")
        elif mode != OFFLINE_MODE:
            failures.append(
                f"the api container's effective {MODE_VARIABLE} is {mode!r}, not {OFFLINE_MODE!r}"
            )
        if api_facts.get("running") is False:
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
            "another real-model execution instance is running: "
            f"{instance['container_name']} ({instance['container_id']}): {instance['reason']}"
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
            "second_real_model_instances": second_instances,
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
    second_real_model_instances: tuple[str, ...]

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
            "second_real_model_instances": list(self.second_real_model_instances),
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
    instances = execution["second_real_model_instances"]
    if not isinstance(instances, list) or instances:
        raise EvidenceRejected(
            "the evidence reports another real-model execution instance (or the field was "
            "tampered with)"
        )
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
        # ``instances`` is empty here (a non-empty list is rejected above): an accepted
        # evidence document only ever records "no second instance", never one that was found.
        second_real_model_instances=tuple(
            str(item.get("container_name", "")) for item in instances if isinstance(item, dict)
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
            "PASS: the public API runs in offline mode and no second real-model execution "
            "instance runs."
        )
    elif verdict == VERDICT_UNKNOWN:
        print(
            "STOP: the review mode or the execution identity of a running container could not "
            "be established. Stop immediately; do not launch supplier calls.",
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
