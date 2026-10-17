"""Isolated real API process that deliberately has no review executor."""

from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings

app = create_app(Settings(_env_file=None))
