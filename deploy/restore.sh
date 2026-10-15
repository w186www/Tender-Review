#!/usr/bin/env bash
# Restore or verify a backup produced by deploy/backup.sh.
#
#   ./deploy/restore.sh <backup-directory> --verify    non-destructive rehearsal (recommended)
#   ./deploy/restore.sh <backup-directory> --confirm   destructive full restore
#
# --verify restores the PostgreSQL dump into a throwaway database and extracts the volume
# archives into throwaway volumes, compares them against the live data, and removes the
# scratch objects. Nothing that is currently running is touched, so a backup can be proven
# restorable without putting live data at risk.
#
# --confirm is the real disaster-recovery path: it drops and recreates the objects it finds
# in the target database and replaces both volumes with the archived content. It refuses to
# run without the flag so it can never fire by accident.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/deploy/.env"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${REPO_ROOT}/docker-compose.demo.yml")
HELPER_IMAGE="${HELPER_IMAGE:-python:3.12-slim-bookworm}"
# Tables that must agree between the restored copy and the live database.
COMPARED_TABLES="tenant app_user project document ingestion_job review_task review_result review_report review_report_content audit_event"

SOURCE="${1:-}"
MODE="${2:-}"
case "${MODE}" in
  --verify|--confirm) ;;
  *) echo "usage: $0 <backup-directory> {--verify|--confirm}" >&2; exit 1 ;;
esac
[ -d "${SOURCE}" ] || { echo "no such backup directory: ${SOURCE}" >&2; exit 1; }
[ -f "${SOURCE}/postgres.dump" ] || { echo "missing postgres.dump in ${SOURCE}" >&2; exit 1; }
[ -f "${ENV_FILE}" ] || { echo "missing ${ENV_FILE}" >&2; exit 1; }

# shellcheck disable=SC1090
set -a; . "${ENV_FILE}"; set +a
PREFIX="${VOLUME_PREFIX:-tender-review}"
DB="${POSTGRES_DB:-bidding_compliance}"
DB_USER="${POSTGRES_USER:-postgres}"

psql_into() { "${COMPOSE[@]}" exec -T postgres psql -q -A -t -U "${DB_USER}" -d "$1" -c "$2"; }

counts() {
  local database="$1" out=""
  for table in ${COMPARED_TABLES}; do
    out="${out}${table}=$(psql_into "${database}" "SELECT count(*) FROM ${table}" 2>/dev/null || echo n/a) "
  done
  printf '%s' "${out}"
}

if [ "${MODE}" = "--verify" ]; then
  SCRATCH="restore_drill_$(date -u +%H%M%S)"
  SCRATCH_VOL="${PREFIX}-verify-$$"
  echo "==> rehearsal: restoring the dump into scratch database ${SCRATCH}"
  "${COMPOSE[@]}" exec -T postgres createdb -U "${DB_USER}" "${SCRATCH}"
  cleanup() {
    "${COMPOSE[@]}" exec -T postgres dropdb --if-exists -U "${DB_USER}" "${SCRATCH}" >/dev/null 2>&1 || true
    docker volume rm "${SCRATCH_VOL}" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT
  "${COMPOSE[@]}" exec -T postgres pg_restore --no-owner --no-privileges \
    --username "${DB_USER}" --dbname "${SCRATCH}" < "${SOURCE}/postgres.dump"

  live="$(counts "${DB}")"
  restored="$(counts "${SCRATCH}")"
  echo "    live     : ${live}"
  echo "    restored : ${restored}"
  verdict_db="passed"
  [ "${live}" = "${restored}" ] || verdict_db="MISMATCH"

  verdict_volumes="passed"
  for archive in miniodata modelstate; do
    [ -f "${SOURCE}/${archive}.tar.gz" ] || { echo "    ${archive}: archive missing"; continue; }
    # Integrity first: the archive must still be the file that was recorded at backup time.
    recorded="$(grep " ${archive}.tar.gz\$" "${SOURCE}/manifest.txt" 2>/dev/null | awk '{print $1}' || true)"
    actual="$(sha256sum "${SOURCE}/${archive}.tar.gz" 2>/dev/null | awk '{print $1}' || true)"
    if [ -n "${recorded}" ] && [ "${recorded}" != "${actual}" ]; then
      echo "    ${archive}: checksum mismatch against manifest"
      verdict_volumes="CORRUPT"
      continue
    fi
    docker volume create "${SCRATCH_VOL}" >/dev/null
    # Streamed through stdin so no host path has to be mounted into the helper container.
    # MSYS_NO_PATHCONV keeps Git Bash from rewriting the container-side /target; harmless
    # on Linux.
    MSYS_NO_PATHCONV=1 docker run --rm -i -v "${SCRATCH_VOL}:/target" --entrypoint tar \
      "${HELPER_IMAGE}" xzf - -C /target < "${SOURCE}/${archive}.tar.gz"
    extract_count="$(MSYS_NO_PATHCONV=1 docker run --rm -v "${SCRATCH_VOL}:/target:ro" \
      --entrypoint sh "${HELPER_IMAGE}" -c 'find /target -type f | wc -l')"
    # Informational only: a live MinIO keeps rewriting its own metadata, so its current file
    # count is not a stable expectation. Object-level proof comes from the post-restore
    # application check (downloading an uploaded original must return the stored digest).
    live_count="$(MSYS_NO_PATHCONV=1 docker run --rm -v "${PREFIX}-${archive}:/source:ro" \
      --entrypoint sh "${HELPER_IMAGE}" -c 'find /source -type f | wc -l' 2>/dev/null || echo 0)"
    echo "    ${archive}: archive files=${extract_count} live files now=${live_count} checksum=ok"
    # An empty archive is only acceptable when the live volume is empty too.
    if [ "${extract_count}" -eq 0 ] && [ "${live_count}" -gt 0 ]; then
      verdict_volumes="EMPTY"
    fi
    docker volume rm "${SCRATCH_VOL}" >/dev/null 2>&1 || true
  done

  echo
  echo "database: ${verdict_db}   volumes: ${verdict_volumes}"
  [ "${verdict_db}" = "passed" ] && [ "${verdict_volumes}" = "passed" ] || exit 1
  echo "rehearsal complete; nothing live was modified"
  exit 0
fi

echo "==> stopping application processes (data plane stays up for the restore)"
"${COMPOSE[@]}" stop worker api nginx

echo "==> restoring PostgreSQL"
"${COMPOSE[@]}" exec -T postgres pg_restore --clean --if-exists --no-owner --no-privileges \
  --username "${DB_USER}" --dbname "${DB}" --single-transaction < "${SOURCE}/postgres.dump"

untar_volume() {
  local archive="$1" volume="$2"
  [ -f "${archive}" ] || { echo "skipping missing $(basename "${archive}")"; return; }
  echo "==> ${volume} <- $(basename "${archive}")"
  MSYS_NO_PATHCONV=1 docker run --rm -i -v "${volume}:/target" --entrypoint sh "${HELPER_IMAGE}" \
    -c 'rm -rf /target/* /target/.[!.]* 2>/dev/null || true; tar xzf - -C /target' \
    < "${archive}"
}

untar_volume "${SOURCE}/miniodata.tar.gz" "${PREFIX}-miniodata"
untar_volume "${SOURCE}/modelstate.tar.gz" "${PREFIX}-modelstate"

echo "==> restarting the stack"
"${COMPOSE[@]}" up -d

echo "==> verifying"
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T api python -c \
    "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)" \
    >/dev/null 2>&1; then
    echo "API is serving again"
    echo "restore complete; sign in and confirm the expected projects and reports are present"
    exit 0
  fi
  sleep 2
done
echo "API did not become healthy after the restore; inspect 'docker compose logs api'" >&2
exit 1
