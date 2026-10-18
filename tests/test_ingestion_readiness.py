"""TASK-0029: readiness waits for fresh signatures without relaxing the scan gate."""

from unittest.mock import Mock

import pytest
from check_ingestion_containers import wait_for_scanner

from bidding_compliance.ingestion.ports import IngestionError


def test_scanner_waits_for_fresh_definitions(monkeypatch):
    monkeypatch.setattr("check_ingestion_containers.time.sleep", lambda _: None)
    scanner = Mock()
    scanner.scan.side_effect = [
        IngestionError("SCANNER_UNAVAILABLE"),
        IngestionError("SCANNER_STALE"),
        None,
    ]
    wait_for_scanner(scanner)
    assert scanner.scan.call_count == 3


@pytest.mark.parametrize("code", ["SCANNER_STALE", "SCANNER_UNAVAILABLE"])
def test_scanner_readiness_deadline_fails_closed(code):
    scanner = Mock()
    scanner.scan.side_effect = IngestionError(code)
    with pytest.raises(RuntimeError, match=code) as caught:
        wait_for_scanner(scanner, timeout_seconds=0)
    assert caught.value.__cause__.code == code
    assert scanner.scan.call_count == 1


def test_scanner_readiness_does_not_retry_malicious_content():
    scanner = Mock()
    scanner.scan.side_effect = IngestionError("MALICIOUS_CONTENT")
    with pytest.raises(IngestionError) as caught:
        wait_for_scanner(scanner)
    assert caught.value.code == "MALICIOUS_CONTENT"
    assert scanner.scan.call_count == 1


def test_scanner_reloads_after_lost_freshclam_notification(monkeypatch):
    monkeypatch.setattr("check_ingestion_containers.time.sleep", lambda _: None)
    scanner = Mock()
    scanner.scan.side_effect = [
        IngestionError("SCANNER_STALE"),
        IngestionError("SCANNER_STALE"),
        None,
    ]
    reload_signatures = Mock()
    wait_for_scanner(scanner, reload_signatures=reload_signatures)
    assert reload_signatures.call_count == 1
    assert scanner.scan.call_count == 3


def test_scanner_reload_is_not_used_for_malicious_content():
    scanner = Mock()
    scanner.scan.side_effect = IngestionError("MALICIOUS_CONTENT")
    reload_signatures = Mock()
    with pytest.raises(IngestionError):
        wait_for_scanner(scanner, reload_signatures=reload_signatures)
    assert reload_signatures.call_count == 0
