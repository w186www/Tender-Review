"""PDF origin maps only through the fixed, bounded TASK-0005 sandbox boundary."""

import base64
import subprocess
import threading
from typing import BinaryIO
from uuid import uuid4

from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.sandbox import DockerParser

from .contracts import SourceExtractionRequest, SourceExtractionResult


class DockerPDFExtractor:
    def __init__(self, image: str) -> None:
        self.parser = DockerParser(image)

    def extract(self, payload: bytes) -> SourceExtractionResult:
        if len(payload) > 2_000_000:
            raise ValueError("PDF source budget exceeded")
        request = SourceExtractionRequest(
            payload_base64=base64.b64encode(payload).decode(), policy=load_policy(),
        ).model_dump_json().encode()
        name = "legal-source-" + uuid4().hex
        process = subprocess.Popen(  # noqa: S603 - fixed sandbox and image/entrypoint only
            [self.parser.executable, *self.parser.options(name), "--entrypoint", "python",
             self.parser.image, "-I", "/app/legal_source_entry.py"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        output = bytearray()
        errors: list[Exception] = []

        def read(stream: BinaryIO | None, limit: int, retain: bool) -> None:
            if stream is None:
                return
            total = 0
            while part := stream.read(65536):
                total += len(part)
                if total > limit:
                    errors.append(ValueError("PDF mapper output budget exceeded"))
                    process.kill()
                    return
                if retain:
                    output.extend(part)

        def write() -> None:
            if process.stdin:
                try:
                    process.stdin.write(request)
                    process.stdin.close()
                except OSError as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=read, args=(process.stdout, 16_000_000, True)),
                   threading.Thread(target=read, args=(process.stderr, 65536, False)),
                   threading.Thread(target=write)]
        try:
            for thread in threads:
                thread.start()
            process.wait(timeout=60)
            for thread in threads:
                thread.join(timeout=5)
            if errors or process.returncode or any(t.is_alive() for t in threads):
                raise ValueError("isolated PDF source extraction failed")
            result = SourceExtractionResult.model_validate_json(output)
            return result
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
            subprocess.run(  # noqa: S603 - only this generated job's container
                [self.parser.executable, "rm", "--force", name],
                capture_output=True, check=False, timeout=10,
            )
