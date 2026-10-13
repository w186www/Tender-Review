"""Resource-limited Docker execution with bounded I/O and cleanup of this job only."""

import base64
import shutil
import subprocess
import threading
from collections import deque
from typing import BinaryIO
from uuid import uuid4

from .ports import IngestionError
from .schemas import FileFormat, IngestionPolicy, ParsedDocument, ParserRequest, ParserResponse


class DockerParser:
    def __init__(self, image: str) -> None:
        import re

        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("A fixed parser image ID is required")
        executable = shutil.which("docker")
        if executable is None:
            raise RuntimeError("Docker runtime required")
        self.executable = executable
        self.image = image

    def options(self, name: str) -> list[str]:
        return [
            "run",
            "--rm",
            "--interactive",
            "--pull=never",
            "--name",
            name,
            "--label",
            "tender-parser=task5",
            "--network=none",
            "--read-only",
            "--user",
            "65532:65532",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=512m",
            "--memory-swap=512m",
            "--cpus=1",
            "--pids-limit=32",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "core=0:0",
            "--ulimit",
            "cpu=60:60",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",  # noqa: S108 - private container-only tmpfs
            "--env",
            "OMP_THREAD_LIMIT=1",
        ]

    def parse(self, payload: bytes, format: FileFormat, policy: IngestionPolicy) -> ParsedDocument:
        request = (
            ParserRequest(
                format=format, payload_base64=base64.b64encode(payload).decode(), policy=policy
            )
            .model_dump_json()
            .encode()
        )
        name = "tender-parser-" + uuid4().hex
        process = subprocess.Popen(  # noqa: S603 - fixed executable, controlled flags and image
            [self.executable, *self.options(name), self.image],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = bytearray()
        errors: deque[Exception] = deque()

        def read(stream: BinaryIO | None, limit: int, retain: bool) -> None:
            if stream is None:
                return
            count = 0
            try:
                while part := stream.read(65536):
                    count += len(part)
                    if count > limit:
                        raise IngestionError("OUTPUT_LIMIT")
                    if retain:
                        output.extend(part)
            except Exception as exc:
                errors.append(exc)
                process.kill()

        def write() -> None:
            if process.stdin is not None:
                try:
                    process.stdin.write(request)
                    process.stdin.close()
                except OSError as exc:
                    errors.append(exc)

        threads = [
            threading.Thread(
                target=read, args=(process.stdout, policy.parser_output_bytes, True), daemon=True
            ),
            threading.Thread(target=read, args=(process.stderr, 65536, False), daemon=True),
            threading.Thread(target=write, daemon=True),
        ]
        try:
            for thread in threads:
                thread.start()
            try:
                process.wait(timeout=policy.parser_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait(timeout=5)
                raise IngestionError("PARSE_TIMEOUT") from exc
            for thread in threads:
                thread.join(timeout=5)
            if any(thread.is_alive() for thread in threads):
                raise IngestionError("PARSE_TIMEOUT")
            for error in errors:
                if isinstance(error, IngestionError):
                    raise error
            if process.returncode != 0 or errors:
                raise IngestionError("PARSE_FAILED")
            try:
                response = ParserResponse.model_validate_json(output)
            except ValueError as exc:
                raise IngestionError("PARSE_FAILED") from exc
            if response.error is not None:
                raise IngestionError(response.error)
            if response.result is None:
                raise IngestionError("PARSE_FAILED")
            return response.result
        finally:
            if process.poll() is None:
                process.kill()
            subprocess.run(  # noqa: S603 - only our random container name; never user input
                [self.executable, "rm", "--force", name],
                capture_output=True,
                check=False,
                timeout=15,
            )
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
