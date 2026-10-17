"""Project legal-library adoption policy and engineering rule/law associations.

The policy records a product decision to use the checked-in legal corpus as the review
reference library. It is deliberately separate from independent legal verification: it
never changes a version's ``verification``/``verified_through`` values, and it never claims
an expert or statutory applicability decision. Citations remain subject to the existing
identity, source, version, applicability and evidence checks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bidding_compliance.domain.rules.engine import SKILLS


@dataclass(frozen=True, slots=True)
class AdoptionPolicy:
    policy_id: str
    decision_ref: str
    adopted_on: str
    manifest_sha256: str
    corpus_index_sha256: str
    version_count: int
    fragment_count: int
    independent_legal_verification: bool
    statement: str
    versions: frozenset[tuple[str, str]]

    def covers(self, law_id: str, version: str) -> bool:
        return (law_id, version) in self.versions


@dataclass(frozen=True, slots=True)
class RuleLawBinding:
    binding_id: str
    rule_id: str
    law_id: str
    version: str
    article: str
    reason: str
    source_reviewed: bool
    asserted_by: str = "engineering-config"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"legal adoption file is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"legal adoption file is not an object: {path}")
    return value


def load_adoption_policy(root: Path) -> AdoptionPolicy | None:
    """Load and verify the policy against the exact checked-in manifest bytes.

    A missing policy is allowed for legacy/test roots; a present but inconsistent policy
    fails closed instead of silently adopting a different corpus.
    """
    policy_path = root / "config/legal/adoption-policy.json"
    manifest_path = root / "config/legal/manifest.json"
    if not policy_path.exists():
        return None
    if not manifest_path.exists():
        raise ValueError("legal adoption policy requires the checked-in manifest")
    policy = _load_json(policy_path)
    if policy.get("schema_version") != "legal-adoption-policy.v1":
        raise ValueError("unsupported legal adoption policy version")
    manifest_raw = manifest_path.read_bytes()
    manifest = _load_json(manifest_path)
    if policy.get("manifest_sha256") != hashlib.sha256(manifest_raw).hexdigest():
        raise ValueError("legal adoption policy does not match the manifest bytes")
    manifest_versions = [
        (str(item["law_id"]), str(item["version"])) for item in manifest.get("versions", [])
    ]
    versions = [
        (str(item["law_id"]), str(item["version"])) for item in policy.get("versions", [])
    ]
    if len(versions) != len(set(versions)) or set(versions) != set(manifest_versions):
        raise ValueError("legal adoption policy does not cover the manifest versions exactly")
    if int(policy.get("version_count", -1)) != len(manifest_versions):
        raise ValueError("legal adoption policy version count mismatch")
    if int(policy.get("fragment_count", -1)) != 3120:
        raise ValueError("legal adoption policy fragment count mismatch")
    if policy.get("independent_legal_verification") is not False:
        raise ValueError("adoption policy must not claim independent legal verification")
    corpus_index = policy.get("corpus_index_sha256")
    if not isinstance(corpus_index, str) or len(corpus_index) != 64:
        raise ValueError("legal adoption policy corpus identity is invalid")
    for key in ("policy_id", "decision_ref", "adopted_on", "statement"):
        if not isinstance(policy.get(key), str) or not policy[key].strip():
            raise ValueError(f"legal adoption policy field is invalid: {key}")
    return AdoptionPolicy(
        policy_id=policy["policy_id"],
        decision_ref=policy["decision_ref"],
        adopted_on=policy["adopted_on"],
        manifest_sha256=policy["manifest_sha256"],
        corpus_index_sha256=corpus_index,
        version_count=len(manifest_versions),
        fragment_count=3120,
        independent_legal_verification=False,
        statement=policy["statement"],
        versions=frozenset(versions),
    )


def load_rule_law_bindings(
    root: Path, policy: AdoptionPolicy
) -> tuple[RuleLawBinding, ...]:
    """Load engineering associations and verify their source text and rule identity.

    The file is configuration, not an expert adjudication. Each association must name a
    real code rule, a manifest version and an article that occurs in that version's checked
    text. Missing or inconsistent configuration fails closed.
    """
    path = root / "config/legal/rule-law-bindings.json"
    if not path.exists():
        raise ValueError("rule-law binding configuration is missing")
    payload = _load_json(path)
    if payload.get("schema_version") != "rule-law-bindings.v1":
        raise ValueError("unsupported rule-law binding version")
    if payload.get("policy_id") != policy.policy_id:
        raise ValueError("rule-law bindings reference a different adoption policy")
    if payload.get("asserted_by") != "engineering-config":
        raise ValueError("rule-law bindings must be engineering configuration, not expert claims")
    known_rules = {
        rule.rule_id for module in SKILLS.values() for rule in module.RULES
    }
    manifest = _load_json(root / "config/legal/manifest.json")
    versions = {
        (str(item["law_id"]), str(item["version"])): item
        for item in manifest.get("versions", [])
    }
    bindings: list[RuleLawBinding] = []
    seen: set[str] = set()
    for item in payload.get("bindings", []):
        if not isinstance(item, dict):
            raise ValueError("rule-law binding entry is invalid")
        binding_id = item.get("binding_id")
        rule_id = item.get("rule_id")
        law_id = item.get("law_id")
        version = item.get("version")
        article = item.get("article")
        reason = item.get("reason")
        if (
            not isinstance(binding_id, str)
            or not binding_id
            or binding_id in seen
            or rule_id not in known_rules
            or (law_id, version) not in versions
            or not isinstance(article, str)
            or not article
            or not isinstance(reason, str)
            or not reason.strip()
            or item.get("source_reviewed") is not True
            or item.get("asserted_by") != "engineering-config"
        ):
            raise ValueError(f"rule-law binding entry is invalid: {binding_id!r}")
        manifest_version = versions[(str(law_id), str(version))]
        text_path = root / str(manifest_version["text_path"])
        try:
            text = text_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"rule-law binding source text is unavailable: {text_path}") from exc
        if article not in text:
            raise ValueError(f"rule-law binding article is absent from the source: {article}")
        seen.add(binding_id)
        bindings.append(
            RuleLawBinding(
                binding_id=binding_id,
                rule_id=str(rule_id),
                law_id=str(law_id),
                version=str(version),
                article=article,
                reason=reason,
                source_reviewed=True,
            )
        )
    if not bindings:
        raise ValueError("rule-law binding configuration is empty")
    return tuple(bindings)


def binding_for(
    bindings: tuple[RuleLawBinding, ...],
    *,
    rule_ids: set[str],
    law_id: str,
    version: str,
    article: str | None,
) -> RuleLawBinding | None:
    if not article:
        return None
    for binding in bindings:
        if (
            binding.rule_id in rule_ids
            and binding.law_id == law_id
            and binding.version == version
            and binding.article == article
        ):
            return binding
    return None
