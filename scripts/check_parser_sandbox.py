"""Verify actual container restrictions with a fixed harmless probe, not uploaded instructions."""

import json
import subprocess
from uuid import uuid4

from bidding_compliance.ingestion.sandbox import DockerParser

PROBE = r"""
import json,os,socket,tempfile,subprocess
private_prefixes=("AUTH_","DATABASE_","OBJECT_STORAGE_")
result={"uid":os.getuid(),"auth_absent":not any(
    k.startswith(private_prefixes) for k in os.environ)}
try:
    open("/sandbox-write-test","w").close()
    result["readonly"]=False
except OSError:
    result["readonly"]=True
try:
    socket.create_connection(("1.1.1.1",53),timeout=1).close()
    result["network_disabled"]=False
except OSError:
    result["network_disabled"]=True
with tempfile.TemporaryDirectory() as folder:
    path=folder+"/probe"
    open(path,"w").write("#!/bin/sh\nexit 0\n")
    os.chmod(path,0o700)
    try:
        subprocess.run([path],check=True,capture_output=True)
        result["tmp_noexec"]=False
    except OSError:
        result["tmp_noexec"]=True
status=dict(line.split(':',1) for line in open('/proc/self/status') if ':' in line)
result["no_privileges"]=(status['CapEff'].strip()=='0000000000000000'
                         and status['NoNewPrivs'].strip()=='1')
result["memory"]=open('/sys/fs/cgroup/memory.max').read().strip()
result["pids"]=open('/sys/fs/cgroup/pids.max').read().strip()
print(json.dumps(result))
"""


def check(image: str) -> None:
    parser = DockerParser(image)
    name = "tender-parser-probe-" + uuid4().hex
    try:
        output = subprocess.run(  # noqa: S603 - fixed harmless probe and controlled image
            [
                parser.executable,
                *parser.options(name),
                "--entrypoint",
                "python",
                image,
                "-I",
                "-c",
                PROBE,
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
        report = json.loads(output.stdout)
        assert report["uid"] == 65532
        assert all(
            report[k]
            for k in ("auth_absent", "readonly", "network_disabled", "tmp_noexec", "no_privileges")
        )
        assert report["memory"] == "536870912" and report["pids"] == "32"
        print(
            "PASS: actual parser sandbox UID, readonly, network, privileges, "
            "tmpfs, memory and PID limits"
        )
    finally:
        subprocess.run(  # noqa: S603 - only our generated verification container
            [parser.executable, "rm", "--force", name],
            capture_output=True,
            timeout=10,
            check=False,
        )


if __name__ == "__main__":
    import os

    check(os.environ["PARSER_VERIFY_IMAGE"])
