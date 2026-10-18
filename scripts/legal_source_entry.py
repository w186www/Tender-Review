"""Fixed, bounded legal PDF extractor inside the existing isolated parser image."""

import base64
import signal
import sys

signal.alarm(65)
sys.path.insert(0, "/app")
from bidding_compliance.legal.contracts import SourceExtractionRequest  # noqa: E402
from bidding_compliance.legal.extraction import extract_pdf_native  # noqa: E402

request = SourceExtractionRequest.model_validate_json(sys.stdin.buffer.read(3_000_001))
result = extract_pdf_native(
    base64.b64decode(request.payload_base64, validate=True), request.policy,
)
sys.stdout.write(result.model_dump_json())
