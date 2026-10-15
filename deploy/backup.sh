#!/usr/bin/env bash
# Consistent backup of everything that cannot be regenerated.
#
#   ./deploy/backup.sh [output-directory]
#
# Captures: the PostgreSQL database (business data, migration version and LangGraph
# checkpoints), the MinIO object volume, and the model budget/audit volume. The ClamAV
# signature database is deliberately excluded: it is re-downloaded and is not business data.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/deploy/.env"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${REPO_ROOT}/docker-compose.demo.yml")

[ -f "${ENV_FILE}" ] || { echo "missing ${ENV_FILE}" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "${ENV_FILE}"; set +a

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${1:-${REPO_ROOT}/backups/${STAMP}}"
PREFIX="${VOLUME_PREFIX:-tender-review}"
HELPER_IMAGE="${HELPER_IMAGE:-python:3.12-slim-bookworm}"

mkdir -p "${TARGET}"
echo "backup target: ${TARGET}"

echo "==> PostgreSQL dump"
# -Fc keeps the dump restorable with pg_restore and independent of the live data directory.
"${COMPOSE[@]}" exec -T postgres \
  pg_dump --format=custom --no-owner --no-privileges \
  --username "${POSTGRES_USER:-postgres}" --dbname "${POSTGRES_DB:-bidding_compliance}" \
  > "${TARGET}/postgres.dump"

tar_volume() {
  local volume="$1" archive="$2"
  echo "==> volume ${volume} -> $(basename "${archive}")"
  # The archive is streamed to stdout instead of bind-mounting the destination, so no
  # second mount point is needed and host paths outside the container never matter.
  # MSYS_NO_PATHCONV is scoped to this one call: Git Bash would otherwise rewrite the
  # container-side /source into a Windows path. It is harmless on Linux.
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "${volume}:/source:ro" \
    --entrypoint tar "${HELPER_IMAGE}" \
    czf - -C /source . > "${archive}"
}

tar_volume "${PREFIX}-miniodata" "${TARGET}/miniodata.tar.gz"
tar_volume "${PREFIX}-modelstate" "${TARGET}/modelstate.tar.gz"

echo "==> manifest"
{
  echo "created_utc=${STAMP}"
  echo "volume_prefix=${PREFIX}"
  echo "database=${POSTGRES_DB:-bidding_compliance}"
  echo "app_image=$(docker image inspect "tender-review-api:${IMAGE_TAG:-demo}" --format '{{.Id}}' 2>/dev/null || echo unknown)"
  echo "web_image=$(docker image inspect "tender-review-web:${IMAGE_TAG:-demo}" --format '{{.Id}}' 2>/dev/null || echo unknown)"
  echo "parser_image=${PARSER_IMAGE:-}"
  echo "compose_file=docker-compose.demo.yml"
  echo
  echo "sha256:"
  (cd "${TARGET}" && sha256sum ./*.dump ./*.tar.gz 2>/dev/null || true)
} > "${TARGET}/manifest.txt"
cat "${TARGET}/manifest.txt"

echo
echo "backup complete: ${TARGET}"
echo "verify a restore before relying on it: ./deploy/restore.sh ${TARGET}"
