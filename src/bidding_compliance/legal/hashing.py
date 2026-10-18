"""Canonical UTF-8 JSON digests for frozen request and result snapshots."""

import hashlib
import json


def canonical_hash(value: object) -> str:
    data = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
