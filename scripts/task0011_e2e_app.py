"""Isolated real FastAPI host with the repository's authorized offline gateway."""

import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_review_engine import OfflineReviewGateway, _policy  # noqa: E402

from bidding_compliance.api import create_app  # noqa: E402
from bidding_compliance.core.config import Settings  # noqa: E402
from bidding_compliance.persistence.database import make_engine  # noqa: E402
from bidding_compliance.services.review_engine import ReviewEngine  # noqa: E402

settings = Settings(_env_file=None)
review_database = make_engine(settings)
review_factory = sessionmaker(review_database, expire_on_commit=False)


class E2EReviewEngine(ReviewEngine):
    async def start(self, principal: Any, request: Any) -> dict[str, Any]:
        try:
            return await super().start(principal, request)
        except Exception:
            logging.getLogger(__name__).exception("Isolated offline ReviewEngine execution failed")
            raise


review_engine = E2EReviewEngine(
    settings=settings,
    session_factory=review_factory,
    gateway=OfflineReviewGateway(),
    model_policy=_policy(),
    legal_root=ROOT,
)
app = create_app(settings, review_engine=review_engine)
