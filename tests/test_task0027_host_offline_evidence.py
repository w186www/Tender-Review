"""Host-side offline evidence: verdicts, key whitelist and the consumer's strict loader.

Every Docker interaction here is synthetic: an injectable runner replays canned ``docker
compose ps`` / ``docker ps`` / ``docker inspect`` documents. No test starts Docker, reads a
real credential or touches a container, and the evidence documents are compared against the
whitelist the generator may ever emit.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import verify_api_offline_mode as host

PROJECT = "tender-review-demo"
API_ID = "1" * 64
WORKER_ID = "2" * 64
OTHER_ID = "3" * 64
SECRET_VALUE = "sk-live-secret-value-must-never-be-recorded"  # noqa: S105 - synthetic
API_IMAGE = "tender-review-api:demo"


class SyntheticDocker:
    """Injectable runner: canned compose ps / docker ps / docker inspect output.

    It records every invocation, so a test can prove that only read-only Docker commands
    were used and that no request ever reached a supplier.
    """

    def __init__(
        self,
        entries: list[dict],
        documents: dict[str, dict],
        *,
        host_ids: list[str] | None = None,
        fail_ids: tuple[str, ...] = (),
    ) -> None:
        self.entries = entries
        self.documents = documents
        self.host_ids = host_ids
        self.fail_ids = set(fail_ids)
        self.invocations: list[list[str]] = []

    def __call__(self, args):
        self.invocations.append(list(args))
        if args[0] == "compose":
            body = "\n".join(json.dumps(entry) for entry in self.entries)
            return host.CommandResult(0, body, "")
        if args[0] == "ps":
            identifiers = self.host_ids or [str(entry["ID"]) for entry in self.entries]
            return host.CommandResult(0, "\n".join(identifiers), "")
        if args[0] == "inspect":
            container_id = args[-1]
            if container_id in self.fail_ids or container_id not in self.documents:
                return host.CommandResult(1, "", f"Error: No such container: {container_id}")
            return host.CommandResult(0, json.dumps([self.documents[container_id]]), "")
        return host.CommandResult(2, "", "unsupported command")


def compose_entry(
    container_id: str,
    name: str,
    service: str,
    *,
    state: str = "running",
    image: str = API_IMAGE,
    project: str = PROJECT,
) -> dict:
    return {
        "Command": "python deploy/api_entry.py",
        "ID": container_id,
        "Image": image,
        "Name": name,
        "Project": project,
        "Service": service,
        "State": state,
    }


def inspect_document(
    container_id: str,
    *,
    name: str,
    image: str = API_IMAGE,
    command: list[str] | None = None,
    entrypoint: list[str] | None = None,
    mode: str | None = "offline",
    app_env: str = "staging",
    state: str = "running",
    running: bool = True,
    health: str | None = None,
    extra_env: tuple[str, ...] = (),
) -> dict:
    environment = ["PATH=/usr/local/bin:/usr/bin", f"DASHSCOPE_API_KEY={SECRET_VALUE}"]
    if mode is not None:
        environment.append(f"DEPLOY_REVIEW_MODE={mode}")
    environment.append(f"APP_ENV={app_env}")
    environment.extend(extra_env)
    document = {
        "Id": container_id,
        "Name": f"/{name}",
        "Image": "sha256:" + "a" * 64,
        "Config": {
            "Image": image,
            "Entrypoint": entrypoint,
            "Cmd": command if command is not None else ["python", "deploy/api_entry.py"],
            "Env": environment,
        },
        "State": {"Status": state, "Running": running},
    }
    if health is not None:
        document["State"]["Health"] = {"Status": health}
    return document


def api_deployment(**overrides) -> SyntheticDocker:
    """One healthy api container plus the offline worker, as the demo stack runs them."""
    entries = [
        compose_entry(API_ID, f"{PROJECT}-api-1", "api"),
        compose_entry(WORKER_ID, f"{PROJECT}-worker-1", "worker"),
    ]
    documents = {
        API_ID: inspect_document(API_ID, name=f"{PROJECT}-api-1", **overrides),
        WORKER_ID: inspect_document(
            WORKER_ID,
            name=f"{PROJECT}-worker-1",
            command=["python", "scripts/run_offline_demo_worker.py"],
            mode="offline",
        ),
    }
    return SyntheticDocker(entries, documents)


def run_generator(
    tmp_path: Path,
    runner,
    *,
    extra_argv: list[str] | None = None,
    now: datetime | None = None,
    evidence_dir: Path | None = None,
) -> tuple[int, Path, Path]:
    destination = evidence_dir or (tmp_path / "evidence")
    moment = now or datetime(2026, 10, 16, 3, 0, 0, tzinfo=UTC)
    argv = [
        "--evidence-dir",
        str(destination),
        "--compose-file",
        "docker-compose.demo.yml",
        "--env-file",
        str(tmp_path / "missing.env"),
        "--expected-image-ref",
        API_IMAGE,
        *(extra_argv or []),
    ]
    exit_code = host.main(argv, runner=runner, now=lambda: moment)
    files = sorted(destination.glob("api-offline-*.json"))
    assert len(files) == 1
    return exit_code, files[0], destination


def read_evidence(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- verdict: ok
def test_a_healthy_offline_api_produces_ok_evidence_without_any_secret(tmp_path, capsys):
    runner = api_deployment()
    exit_code, path, _destination = run_generator(tmp_path, runner)
    assert exit_code == host.EXIT_CODE[host.VERDICT_OK] == 0
    evidence = read_evidence(path)
    assert path.name.startswith("api-offline-20261016T030000Z")
    assert evidence["verdict"] == host.VERDICT_OK
    assert evidence["schema_version"] == host.SCHEMA_VERSION
    assert evidence["checked_at"] == "2026-10-16T03:00:00Z"
    assert evidence["compose_project"] == PROJECT
    assert evidence["docker_binary"] == "docker"
    api = evidence["api"]
    assert api["container_id"] == API_ID
    assert api["container_name"] == f"{PROJECT}-api-1"
    assert api["deploy_review_mode"] == "offline"
    assert api["app_env"] == "staging"
    assert api["image_reference"] == API_IMAGE
    assert api["image_id"] == "sha256:" + "a" * 64
    assert api["command"] == ["python", "deploy/api_entry.py"]
    assert api["entrypoint"] == []
    assert api["state"] == "running" and api["running"] is True
    assert api["health_status"] == host.HEALTH_ABSENT
    assert evidence["execution_instances"] == {
        "scanned_container_count": 2,
        "authorized_real_instances": [],
    }
    assert evidence["checks"] == {
        "review_mode_offline": True,
        "container_running": True,
        "health_acceptable": True,
        "image_expected": True,
        "entrypoint_expected": True,
        "no_second_authorized_real_instance": True,
    }
    assert evidence["failures"] == []
    printed = capsys.readouterr()
    assert "verdict: ok" in printed.out
    # The evidence document and the terminal output are limited to the whitelist: the
    # supplier credential injected into the container environment never leaves the loop.
    text = path.read_text(encoding="utf-8") + printed.out + printed.err
    assert SECRET_VALUE not in text
    assert "DASHSCOPE_API_KEY" not in text
    assert "PATH=" not in text


def test_the_evidence_key_set_is_exactly_the_whitelist(tmp_path):
    _exit_code, path, _destination = run_generator(tmp_path, api_deployment())
    evidence = read_evidence(path)
    assert set(evidence) == set(host.EVIDENCE_KEYS)
    assert set(evidence["api"]) == set(host.API_KEYS)
    assert set(evidence["execution_instances"]) == set(host.EXECUTION_KEYS)
    assert set(evidence["checks"]) == set(host.CHECK_KEYS)


# ---------------------------------------------------------------- verdict: untrusted
def test_a_second_authorized_real_instance_is_untrusted(tmp_path, capsys):
    runner = api_deployment()
    runner.entries.append(compose_entry(OTHER_ID, f"{PROJECT}-api-run-abc", "api"))
    runner.documents[OTHER_ID] = inspect_document(
        OTHER_ID,
        name=f"{PROJECT}-api-run-abc",
        mode="authorized-real",
        command=["python", "scripts/task0027_real_ai_validation_app.py"],
    )
    runner.host_ids = [API_ID, WORKER_ID, OTHER_ID]
    exit_code, path, _destination = run_generator(tmp_path, runner)
    assert exit_code == host.EXIT_CODE[host.VERDICT_UNTRUSTED] == 3
    evidence = read_evidence(path)
    assert evidence["verdict"] == host.VERDICT_UNTRUSTED
    assert evidence["checks"]["no_second_authorized_real_instance"] is False
    assert evidence["execution_instances"]["authorized_real_instances"] == [
        {"container_name": f"{PROJECT}-api-run-abc", "container_id": OTHER_ID}
    ]
    assert any("authorized-real" in failure for failure in evidence["failures"])
    assert "do not launch supplier calls" in capsys.readouterr().err


def test_an_api_that_serves_authorized_real_is_untrusted(tmp_path, capsys):
    runner = api_deployment(mode="authorized-real")
    exit_code, path, _destination = run_generator(tmp_path, runner)
    assert exit_code == 3
    evidence = read_evidence(path)
    assert evidence["verdict"] == host.VERDICT_UNTRUSTED
    assert evidence["checks"]["review_mode_offline"] is False
    assert any("authorized-real" in failure for failure in evidence["failures"])
    assert "do not launch supplier calls" in capsys.readouterr().err


def test_a_stopped_container_or_a_foreign_image_is_untrusted(tmp_path):
    stopped = api_deployment(running=False, state="exited")
    stopped.entries[0]["State"] = "exited"
    exit_code, path, _destination = run_generator(tmp_path, stopped, evidence_dir=tmp_path / "a")
    assert exit_code == 3
    assert read_evidence(path)["checks"]["container_running"] is False

    foreign = api_deployment(image="tender-review-api:task0027-validation")
    exit_code, path, _destination = run_generator(
        tmp_path, foreign, evidence_dir=tmp_path / "b"
    )
    assert exit_code == 3
    assert read_evidence(path)["checks"]["image_expected"] is False

    wrong_command = api_deployment(command=["python", "scripts/prebuild_legal_vectors.py"])
    exit_code, path, _destination = run_generator(
        tmp_path, wrong_command, evidence_dir=tmp_path / "c"
    )
    assert exit_code == 3
    assert read_evidence(path)["checks"]["entrypoint_expected"] is False


def test_a_container_entrypoint_that_overrides_the_image_is_untrusted(tmp_path):
    runner = api_deployment(entrypoint=["python"])
    exit_code, path, _destination = run_generator(tmp_path, runner)
    assert exit_code == 3
    assert read_evidence(path)["checks"]["entrypoint_expected"] is False


# -------------------------------------------------------------------- verdict: unknown
def test_a_missing_effective_mode_is_unknown(tmp_path, capsys):
    runner = api_deployment(mode=None)
    exit_code, path, _destination = run_generator(tmp_path, runner)
    assert exit_code == host.EXIT_CODE[host.VERDICT_UNKNOWN] == 2
    evidence = read_evidence(path)
    assert evidence["verdict"] == host.VERDICT_UNKNOWN
    assert evidence["api"]["deploy_review_mode"] == ""
    assert evidence["checks"]["review_mode_offline"] is False
    captured = capsys.readouterr()
    assert "Stop immediately; do not launch supplier calls" in captured.err


def test_a_failed_inspect_is_unknown(tmp_path, capsys):
    runner = api_deployment()
    runner.fail_ids = {API_ID}
    exit_code, path, _destination = run_generator(tmp_path, runner)
    assert exit_code == 2
    evidence = read_evidence(path)
    assert evidence["verdict"] == host.VERDICT_UNKNOWN
    assert any("could not be inspected" in failure for failure in evidence["failures"])
    assert "Stop immediately; do not launch supplier calls" in capsys.readouterr().err


def test_an_absent_api_container_is_unknown(tmp_path):
    entries = [compose_entry(WORKER_ID, f"{PROJECT}-worker-1", "worker")]
    documents = {WORKER_ID: inspect_document(WORKER_ID, name=f"{PROJECT}-worker-1")}
    runner = SyntheticDocker(entries, documents)
    exit_code, path, _destination = run_generator(tmp_path, runner)
    assert exit_code == 2
    evidence = read_evidence(path)
    assert evidence["verdict"] == host.VERDICT_UNKNOWN
    assert evidence["api"]["container_id"] == ""
    assert any("no running container" in failure for failure in evidence["failures"])


# ---------------------------------------------------------- read-only, injectable seam
def test_only_read_only_docker_commands_are_ever_used(tmp_path):
    runner = api_deployment()
    run_generator(tmp_path, runner)
    assert runner.invocations
    for invocation in runner.invocations:
        assert host.is_read_only(invocation), invocation
        assert invocation[0] in {"compose", "ps", "inspect"}
        for forbidden in ("run", "exec", "create", "start", "stop", "rm", "kill", "up", "down"):
            assert forbidden not in invocation, (forbidden, invocation)
    assert any(
        invocation[0] == "compose" and "ps" in invocation for invocation in runner.invocations
    )
    assert any(invocation[:2] == ["ps", "-aq"] for invocation in runner.invocations)
    assert any(invocation[0] == "inspect" for invocation in runner.invocations)


def test_the_fixture_runner_reads_the_documented_file_names(tmp_path):
    assert host.fixture_name(["compose", "ps", "--all"]) == "compose-ps.json"
    assert host.fixture_name(["ps", "-aq", "--no-trunc"]) == "docker-ps.json"
    assert (
        host.fixture_name(["inspect", "--type", "container", API_ID])
        == f"inspect-{API_ID}.json"
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    runner = host.fixture_runner(fixtures)
    assert runner(["compose", "ps"]).returncode == 1  # absent fixture is reported, never faked
    (fixtures / "compose-ps.json").write_text(
        json.dumps(compose_entry(API_ID, f"{PROJECT}-api-1", "api")), encoding="utf-8"
    )
    (fixtures / "docker-ps.json").write_text(API_ID, encoding="utf-8")
    (fixtures / f"inspect-{API_ID}.json").write_text(
        json.dumps([inspect_document(API_ID, name=f"{PROJECT}-api-1")]), encoding="utf-8"
    )
    exit_code, path, _destination = run_generator(
        tmp_path, runner, extra_argv=["--fixture-dir", str(fixtures)]
    )
    assert exit_code == 0
    evidence = read_evidence(path)
    assert evidence["docker_binary"] == f"fixture:{fixtures}"
    assert evidence["verdict"] == host.VERDICT_OK


def test_the_real_subprocess_runner_reports_a_failure_instead_of_crashing(tmp_path):
    """The subprocess seam itself: a docker binary that cannot run yields unknown, no raise."""
    exit_code = host.main(
        [
            "--docker-bin",
            sys.executable,
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--compose-file",
            "docker-compose.demo.yml",
            "--env-file",
            str(tmp_path / "missing.env"),
        ],
        now=lambda: datetime(2026, 10, 16, 3, 0, 0, tzinfo=UTC),
    )
    assert exit_code == 2
    files = sorted((tmp_path / "evidence").glob("api-offline-*.json"))
    assert len(files) == 1
    evidence = read_evidence(files[0])
    assert evidence["verdict"] == host.VERDICT_UNKNOWN
    assert evidence["docker_binary"] == sys.executable


# ------------------------------------------------------------------ the strict loader
def accept(tmp_path, evidence: dict, **overrides):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    arguments = {
        "max_age_seconds": 600,
        "expected_api_container_id": API_ID,
        "expected_compose_project": PROJECT,
        "now": datetime(2026, 10, 16, 3, 5, 0, tzinfo=UTC),
    }
    arguments.update(overrides)
    return host.load_evidence(path, **arguments)  # type: ignore[arg-type]


def fresh_evidence(tmp_path) -> dict:
    runner = api_deployment()
    _exit_code, path, _destination = run_generator(tmp_path, runner)
    return read_evidence(path)


def test_the_loader_accepts_a_fresh_ok_document_and_reports_the_age(tmp_path):
    accepted = accept(tmp_path, fresh_evidence(tmp_path), max_age_seconds=3600)
    assert accepted.deploy_review_mode == "offline"
    assert accepted.compose_project == PROJECT
    assert accepted.api_container_id == API_ID
    assert accepted.api_image_reference == API_IMAGE
    assert accepted.age_seconds == 300.0
    assert accepted.second_authorized_real_instances == ()
    assert accepted.as_payload()["max_age_seconds"] == 3600


@pytest.mark.parametrize("verdict", ["unknown", "untrusted"])
def test_the_loader_rejects_any_non_ok_verdict(tmp_path, verdict):
    evidence = fresh_evidence(tmp_path)
    evidence["verdict"] = verdict
    with pytest.raises(host.EvidenceRejected, match="do not launch supplier calls"):
        accept(tmp_path, evidence)


def test_the_loader_rejects_a_stale_or_future_document(tmp_path):
    evidence = fresh_evidence(tmp_path)
    with pytest.raises(host.EvidenceRejected, match="freshness window"):
        accept(tmp_path, evidence, now=datetime(2026, 10, 16, 4, 0, 0, tzinfo=UTC))
    evidence["checked_at"] = (
        datetime(2026, 10, 16, 3, 5, 0, tzinfo=UTC) + timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(host.EvidenceRejected, match="future"):
        accept(tmp_path, evidence)


def test_the_loader_rejects_a_different_container_or_project(tmp_path):
    evidence = fresh_evidence(tmp_path)
    with pytest.raises(host.EvidenceRejected, match="different api container"):
        accept(tmp_path, evidence, expected_api_container_id="9" * 64)
    with pytest.raises(host.EvidenceRejected, match="different compose project"):
        accept(tmp_path, evidence, expected_compose_project="other-project")
    # A short form of the same container id is accepted; a 64-hex id that only shares the
    # first twelve characters is still a different container.
    accepted = accept(tmp_path, evidence, expected_api_container_id=API_ID[:12])
    assert accepted.api_container_id == API_ID
    with pytest.raises(host.EvidenceRejected, match="different api container"):
        accept(tmp_path, evidence, expected_api_container_id=API_ID[:12] + "0" * 52)


def test_the_loader_rejects_an_unexpected_field_a_bad_mode_or_a_second_instance(tmp_path):
    evidence = fresh_evidence(tmp_path)
    tampered = {**evidence, "environment": {"DASHSCOPE_API_KEY": SECRET_VALUE}}
    with pytest.raises(host.EvidenceRejected, match="unexpected fields"):
        accept(tmp_path, tampered)
    tampered_api = json.loads(json.dumps(evidence))
    del tampered_api["api"]["health_status"]
    with pytest.raises(host.EvidenceRejected, match="missing fields"):
        accept(tmp_path, tampered_api)
    online_api = json.loads(json.dumps(evidence))
    online_api["api"]["deploy_review_mode"] = "authorized-real"
    with pytest.raises(host.EvidenceRejected, match="expected 'offline'"):
        accept(tmp_path, online_api)
    second = json.loads(json.dumps(evidence))
    second["execution_instances"]["authorized_real_instances"] = ["other"]
    with pytest.raises(host.EvidenceRejected, match="another authorized-real instance"):
        accept(tmp_path, second)
    not_running = json.loads(json.dumps(evidence))
    not_running["api"]["running"] = False
    with pytest.raises(host.EvidenceRejected, match="not running"):
        accept(tmp_path, not_running)


def test_the_loader_requires_the_current_identity_and_bounds_the_window(tmp_path):
    evidence = fresh_evidence(tmp_path)
    with pytest.raises(host.EvidenceRejected, match="current api container id is required"):
        accept(tmp_path, evidence, expected_api_container_id="")
    with pytest.raises(host.EvidenceRejected, match="current compose project is required"):
        accept(tmp_path, evidence, expected_compose_project="  ")
    with pytest.raises(host.EvidenceRejected, match="60..3600"):
        accept(tmp_path, evidence, max_age_seconds=30)
    with pytest.raises(host.EvidenceRejected, match="60..3600"):
        accept(tmp_path, evidence, max_age_seconds=7200)


def test_the_loader_rejects_a_missing_unparseable_or_unbounded_document(tmp_path):
    with pytest.raises(host.EvidenceRejected, match="no host offline evidence was given"):
        host.load_evidence(
            "",
            max_age_seconds=600,
            expected_api_container_id=API_ID,
            expected_compose_project=PROJECT,
        )
    with pytest.raises(host.EvidenceRejected, match="is absent"):
        host.load_evidence(
            tmp_path / "no-such-evidence.json",
            max_age_seconds=600,
            expected_api_container_id=API_ID,
            expected_compose_project=PROJECT,
        )
    broken = tmp_path / "evidence.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(host.EvidenceRejected, match="not a JSON document"):
        host.load_evidence(
            broken,
            max_age_seconds=600,
            expected_api_container_id=API_ID,
            expected_compose_project=PROJECT,
        )
    array = tmp_path / "array.json"
    array.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(host.EvidenceRejected, match="not a JSON object"):
        host.load_evidence(
            array,
            max_age_seconds=600,
            expected_api_container_id=API_ID,
            expected_compose_project=PROJECT,
        )
    naive = fresh_evidence(tmp_path)
    naive["checked_at"] = "2026-10-16T03:00:00"
    with pytest.raises(host.EvidenceRejected, match="no timezone"):
        accept(tmp_path, naive)
