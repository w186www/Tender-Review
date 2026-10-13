"""Fixed image entrypoint; no arguments, host environment imports or dynamic modules."""

import signal
import sys

signal.alarm(65)

sys.path.insert(0, "/app")
from bidding_compliance.ingestion.parser import main  # noqa: E402

main()
