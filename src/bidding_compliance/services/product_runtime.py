"""Explicit product-mode assembly: PostgreSQL authorization and budget authorities.

This module contains no business logic of its own beyond wiring the existing gateway,
review engine and API. It refuses to start when the product authority is incomplete, and
it never falls back to the legacy JSONL/SQLite authorization path.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings
from bidding_compliance.legal.adoption import load_adoption_policy
from bidding_compliance.model_gateway.adapters.bailian_qwen_adapter import BailianQwenChatAdapter
from bidding_compliance.model_gateway.authorization import AuthorizationPolicy
from bidding_compliance.model_gateway.authorized_runtime import MetadataAuditSink
from bidding_compliance.model_gateway.contracts import DataPolicy
from bidding_compliance.model_gateway.gateway import ModelGatewayService
from bidding_compliance.model_gateway.postgres_budget import PostgresBudgetLedger
from bidding_compliance.model_gateway.routing import ModelTarget, ProfileRouter
from bidding_compliance.services.execution_authorization import (
    PostgresAuthorizationGate,
    require_execution_policy,
)
from bidding_compliance.services.real_ai_runtime import (
    DISCOVERY_EVIDENCE_PROMPT,
    DISCOVERY_PROMPT,
    DISCOVERY_PROMPT_VERSION,
    FULLTEXT_V1_PROMPT,
    LEGACY_SEMANTIC_PROMPT,
    LEGACY_SEMANTIC_PROMPT_VERSION,
    PREVIOUS_SEMANTIC_PROMPT,
    PREVIOUS_SEMANTIC_PROMPT_VERSION,
    SEMANTIC_PROMPT,
    SEMANTIC_PROMPT_VERSION,
    AuthorizedRealReviewEngine,
    AuthorizedTenderMinimizer,
    real_ai_policy,
)
from bidding_compliance.services.real_embedding_runtime import create_real_retriever_factory
from bidding_compliance.services.review_contracts import (
    DISCOVERY_EVIDENCE_PROMPT_VERSION,
    FULLTEXT_V1_PROMPT_VERSION,
)


@dataclass(frozen=True, slots=True)
class ProductRuntime:
    app: FastAPI
    engine: AuthorizedRealReviewEngine
    budget: PostgresBudgetLedger
    gate: PostgresAuthorizationGate
    reconciliation: dict[str, int]


def create_product_runtime(
    *,
    settings: Settings,
    database: Engine,
    tenant_id: str,
    provider: str,
    purpose: str,
    model: str,
    api_key: str,
    workspace_id: str,
    budget_authorization_id: str,
    private_root: Path,
    transport: httpx.AsyncBaseTransport | None = None,
    embed_transport: httpx.BaseTransport | None = None,
    allow_vector_build: bool = False,
) -> ProductRuntime:
    """Wire the product authority; any missing or inconsistent precondition fails closed."""
    if not tenant_id or not provider or not purpose or not budget_authorization_id:
        raise ValueError("product tenant, provider, purpose and budget identity are required")
    if not api_key.strip() or not workspace_id.strip():
        raise ValueError("product mode requires server-side supplier credentials")
    session_factory = sessionmaker(database, expire_on_commit=False)
    with session_factory() as session:
        policy = require_execution_policy(session, tenant_id, provider=provider, purpose=purpose)
    budget = PostgresBudgetLedger(
        session_factory,
        tenant_id=tenant_id,
        authorization_id=budget_authorization_id,
        max_call_cny=policy.max_call_cny,
        max_embedding_batch_cny=policy.max_embedding_batch_cny,
    )
    account = budget.verify_account()
    if Decimal(account["limit_cny"]) != policy.budget_cny:
        raise ValueError("the tenant policy budget and the PostgreSQL budget account limit differ")
    gate = PostgresAuthorizationGate(
        session_factory,
        tenant_id=tenant_id,
        purpose=purpose,
        provider=provider,
    )
    authorization = AuthorizationPolicy(
        trusted_calls={},
        tenant_providers={tenant_id: frozenset({provider})},
        provider_data_policies={provider: frozenset({DataPolicy.CONFIDENTIAL})},
    )
    minimizer = AuthorizedTenderMinimizer(gate.allowed_hashes)
    gateway = ModelGatewayService(
        router=ProfileRouter(
            {
                real_ai_policy().profile: (
                    ModelTarget(
                        provider=provider,
                        model=model,
                        input_cost_per_million=Decimal("0.8"),
                        output_cost_per_million=Decimal("2.7"),
                        pricing_version="product-postgres-2026-10-17",
                        max_cost_per_call=policy.max_call_cny,
                        config_version="task0028-u05-v1",
                        schema_supported=True,
                    ),
                )
            }
        ),
        adapters={provider: BailianQwenChatAdapter(api_key, workspace_id, transport=transport)},
        authorization=authorization,
        budgets=budget,
        approved_prompts={
            DISCOVERY_PROMPT_VERSION: DISCOVERY_PROMPT,
            DISCOVERY_EVIDENCE_PROMPT_VERSION: DISCOVERY_EVIDENCE_PROMPT,
            SEMANTIC_PROMPT_VERSION: SEMANTIC_PROMPT,
            FULLTEXT_V1_PROMPT_VERSION: FULLTEXT_V1_PROMPT,
            PREVIOUS_SEMANTIC_PROMPT_VERSION: PREVIOUS_SEMANTIC_PROMPT,
            LEGACY_SEMANTIC_PROMPT_VERSION: LEGACY_SEMANTIC_PROMPT,
        },
        audit_sink=MetadataAuditSink(private_root / "product-model-audit.jsonl"),
        input_minimizer=minimizer,
        max_concurrent_per_provider=1,
    )
    reconciliation = budget.reconcile_orphaned()
    legal_root = Path(__file__).resolve().parents[3]
    review_engine = AuthorizedRealReviewEngine(
        settings=settings,
        session_factory=session_factory,
        gateway=gateway,
        model_policy=real_ai_policy(),
        legal_root=legal_root,
        authorization=authorization,
        allowed_document_sha256=gate.allowed_hashes,
        document_authorization=gate,
        unknown_call_callback=budget.mark_call_unknown,
        retriever_factory=create_real_retriever_factory(
            api_key=api_key,
            workspace_id=workspace_id,
            budget=budget,
            private_root=private_root,
            client=httpx.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=20,
                transport=embed_transport,
            ),
            allow_build=allow_vector_build,
            adoption_policy=load_adoption_policy(legal_root),
        ),
    )
    app = create_app(settings, review_engine=review_engine)
    app.state.review_prompt_version = SEMANTIC_PROMPT_VERSION
    app.state.external_budget = budget
    app.state.authorization_id = budget_authorization_id
    app.state.external_authorization_mode = "postgres"
    app.state.external_authorization_purpose = purpose
    app.state.external_authorization_provider = provider
    app.state.product_tenant_id = tenant_id
    return ProductRuntime(
        app=app,
        engine=review_engine,
        budget=budget,
        gate=gate,
        reconciliation=reconciliation,
    )
