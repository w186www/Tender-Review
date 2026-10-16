#!/usr/bin/env bash
#
# Host-side, read-only evidence that the public API still runs DEPLOY_REVIEW_MODE=offline.
#
# Run this ON THE HOST (never inside a container) before a controlled real-model round, then
# pass the evidence file to the validation entry point:
#
#   bash deploy/verify_api_offline_mode.sh --evidence-dir /opt/tender-review-private/evidence
#   ... --host-offline-evidence /opt/tender-review-private/evidence/api-offline-<ts>.json
#
# The script performs only read-only Docker operations -- `docker compose ... ps`, `docker ps`
# and `docker inspect` -- and writes one JSON evidence document. It never creates, starts,
# stops, removes or enters a container, never mounts the Docker socket anywhere and never
# hands Docker access to any container. Only two non-secret environment values of the api
# container (DEPLOY_REVIEW_MODE, APP_ENV) are ever recorded; no other variable and no
# credential is read, printed or stored.
#
# It checks every container on the host, not only the api one: a running container counts as
# a second real-model execution instance when its effective DEPLOY_REVIEW_MODE is
# authorized-real, when its start command runs task0023_real_ai_app (authorized-real assembly)
# or task0027_real_ai_validation_app (isolated validation entry), when it runs
# deploy/api_entry.py with DEPLOY_REVIEW_MODE=authorized-real, or when its image carries the
# task0027-validation tag. When the execution identity of a running container cannot be read
# (failed inspect, missing fields, unreadable command), the verdict is unknown -- never ok.
#
# Exit codes: 0 = verdict ok, 2 = verdict unknown (stop immediately, do not launch supplier
# calls), 3 = verdict untrusted (same). The evidence file is written for every verdict.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
implementation="${script_dir}/verify_api_offline_mode.py"

if [[ ! -f "${implementation}" ]]; then
    echo "STOP: ${implementation} is missing; run this script from a full checkout." >&2
    exit 2
fi

# The host may only have a bare python3 (this script imports nothing outside the standard
# library on purpose); PYTHON_BIN overrides the lookup for an unusual host.
python_bin="${PYTHON_BIN:-}"
if [[ -z "${python_bin}" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        python_bin="python3"
    elif command -v python >/dev/null 2>&1; then
        python_bin="python"
    else
        echo "STOP: python3 is required on the host to inspect the deployment." >&2
        exit 2
    fi
fi

exec "${python_bin}" "${implementation}" "$@"
