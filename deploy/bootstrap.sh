#!/usr/bin/env bash
# Idempotent deployment bootstrap for the single-host demo stack.
#
#   ./deploy/bootstrap.sh init        generate deploy/.env, build images, start in order
#   ./deploy/bootstrap.sh parser      (re)build the isolated parser image and pin its ID
#   ./deploy/bootstrap.sh up          start the stack in the required order
#   ./deploy/bootstrap.sh credentials print the demo accounts
#
# Requires: docker with the compose plugin. Everything else runs in containers.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/deploy/.env"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${REPO_ROOT}/docker-compose.demo.yml")
PARSER_IMAGE_TAG="tender-review-parser:demo"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || fail "docker is not installed"
  docker info >/dev/null 2>&1 || fail "the Docker daemon is not reachable"
  docker compose version >/dev/null 2>&1 || fail "the docker compose plugin is missing"
}

secret() {
  local bytes="${1:-24}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "${bytes}"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets,sys;sys.stdout.write(secrets.token_hex(${bytes}))"
  else
    fail "neither openssl nor python3 is available to generate secrets"
  fi
}

write_env() {
  if [ -f "${ENV_FILE}" ]; then
    log "keeping the existing ${ENV_FILE} (delete it to regenerate every secret)"
    return
  fi
  log "generating ${ENV_FILE} with fresh secrets"
  local pg minio_key minio_secret runtime signing admin reviewer auditor
  pg="$(secret 24)"
  minio_key="$(secret 12)"
  minio_secret="$(secret 24)"
  runtime="$(secret 24)"
  signing="$(secret 32)"
  admin="$(secret 12)"
  reviewer="$(secret 12)"
  auditor="$(secret 12)"

  umask 077
  sed \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pg}|" \
    -e "s|^DEMO_DB_RUNTIME_PASSWORD=.*|DEMO_DB_RUNTIME_PASSWORD=${runtime}|" \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://tender_runtime:${runtime}@postgres:5432/bidding_compliance|" \
    -e "s|^ADMIN_DATABASE_URL=.*|ADMIN_DATABASE_URL=postgresql+psycopg://postgres:${pg}@postgres:5432/bidding_compliance|" \
    -e "s|^MINIO_ROOT_USER=.*|MINIO_ROOT_USER=${minio_key}|" \
    -e "s|^MINIO_ROOT_PASSWORD=.*|MINIO_ROOT_PASSWORD=${minio_secret}|" \
    -e "s|^AUTH_SIGNING_KEY=.*|AUTH_SIGNING_KEY=${signing}|" \
    -e "s|^DEMO_ADMIN_PASSWORD=.*|DEMO_ADMIN_PASSWORD=${admin}|" \
    -e "s|^DEMO_REVIEWER_PASSWORD=.*|DEMO_REVIEWER_PASSWORD=${reviewer}|" \
    -e "s|^DEMO_AUDITOR_PASSWORD=.*|DEMO_AUDITOR_PASSWORD=${auditor}|" \
    "${REPO_ROOT}/deploy/demo.env.example" > "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  printf '   generated credentials are in %s\n' "${ENV_FILE}"
}

set_env_value() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

build_parser_image() {
  log "building the isolated parser image (Tesseract + pinned parser lock)"
  docker build -f "${REPO_ROOT}/Dockerfile.parser" -t "${PARSER_IMAGE_TAG}" "${REPO_ROOT}"
  local image_id
  image_id="$(docker image inspect --format '{{.Id}}' "${PARSER_IMAGE_TAG}")"
  # The worker refuses anything that is not a fixed image ID (ingestion/sandbox.py).
  set_env_value PARSER_IMAGE "${image_id}"
  printf '   PARSER_IMAGE=%s\n' "${image_id}"
}

wait_for_init() {
  log "initialising database, RLS role, accounts, bucket and scanner"
  # A dedicated one-shot service carries the superuser DSN and the account passwords, so
  # the long-running API container never holds them.
  "${COMPOSE[@]}" --profile init run --rm init deploy/demo_init.py storage
}

verify_legal_checkout() {
  # .gitattributes pins knowledge/legal/**/*.txt to CRLF because the hashes recorded in
  # config/legal/manifest.json were captured from CRLF files. Switching branches does not
  # re-smudge files that are already checked out (their normalised content still matches
  # the index), so a clone that started on a branch without that rule keeps LF bytes and
  # every corpus hash then mismatches. The corpus is baked into the API image, so catching
  # it here is far cheaper than the opaque 422 the API returns later.
  local bad
  bad="$(git -C "${REPO_ROOT}" ls-files --eol knowledge/legal 2>/dev/null \
    | awk '$1 == "i/lf" && $2 == "w/lf" && /eol=crlf/ {n++} END {print n + 0}')"
  if [ "${bad}" != "0" ]; then
    fail "legal corpus line endings are wrong: ${bad} files are LF but must be CRLF.
       Fix with:
         rm -rf ${REPO_ROOT}/knowledge/legal && git -C ${REPO_ROOT} checkout -- knowledge/legal
       then re-run './deploy/bootstrap.sh init'. The API image bakes this corpus in, so it
       must be rebuilt afterwards as well."
  fi
  printf '   legal corpus line endings verified\n'
}

detect_socket_gid() {
  # The ingestion worker runs as uid 65532 and talks to the Docker socket to start the
  # sandboxed parser. The socket's owning group differs per host (root on Docker Desktop,
  # docker on a typical Linux install), so read it instead of guessing.
  local gid
  # MSYS_NO_PATHCONV keeps Git Bash from rewriting the container-side socket path. It is
  # scoped to this call only, so every other path stays in the form docker.exe expects.
  gid="$(MSYS_NO_PATHCONV=1 docker run --rm --entrypoint stat \
    -v /var/run/docker.sock:/var/run/docker.sock:ro \
    "tender-review-api:${IMAGE_TAG:-demo}" -c '%g' /var/run/docker.sock 2>/dev/null || true)"
  if ! printf '%s' "${gid}" | grep -Eq '^[0-9]+$'; then
    printf '   could not read the docker socket group; falling back to 0\n'
    gid=0
  fi
  set_env_value DOCKER_SOCKET_GID "${gid}"
  printf '   DOCKER_SOCKET_GID=%s\n' "${gid}"
}

bootstrap() {
  require_docker
  write_env
  log "verifying the checked-out legal corpus before it gets baked into the images"
  verify_legal_checkout
  build_parser_image
  log "building application and web images"
  "${COMPOSE[@]}" build api nginx
  log "resolving the docker socket group for the ingestion worker"
  detect_socket_gid
  log "starting data plane (PostgreSQL, MinIO, ClamAV)"
  "${COMPOSE[@]}" up -d postgres minio clamav
  wait_for_init
  log "starting application plane (API, ingestion worker, reverse proxy)"
  "${COMPOSE[@]}" up -d api worker nginx
  wait_for_api
  "${COMPOSE[@]}" --profile init run --rm init deploy/demo_init.py legal
  credentials
}

wait_for_api() {
  # The legal publication is created through the real authenticated API, so it must run
  # after the API is serving.
  for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T api python -c \
      "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail "the API did not become healthy; inspect 'docker compose logs api'"
}

up() {
  require_docker
  [ -f "${ENV_FILE}" ] || fail "run './deploy/bootstrap.sh init' first"
  # A restart must never leave the worker without its parser image.
  if ! grep -Eq '^PARSER_IMAGE=sha256:[a-f0-9]{64}$' "${ENV_FILE}"; then
    log "no pinned parser image recorded; building one"
    build_parser_image
  fi
  "${COMPOSE[@]}" up -d postgres minio clamav
  wait_for_init
  # review-worker claims the durable review queue; without it every review stays queued.
  "${COMPOSE[@]}" up -d api review-worker worker nginx
  wait_for_api
  # Idempotent: skips when the tenant already has an active publication. Also repairs a
  # database that was restored from a backup taken before the publication existed.
  "${COMPOSE[@]}" --profile init run --rm init deploy/demo_init.py legal
  log "stack started"
  "${COMPOSE[@]}" ps
}

credentials() {
  # Never print secrets. Bootstrap output is routinely captured by remote-execution
  # tooling and CI logs, so the account passwords stay in deploy/.env (mode 600) and are
  # only read by an operator on the host itself.
  [ -f "${ENV_FILE}" ] || fail "run './deploy/bootstrap.sh init' first"
  local port
  port="$(grep '^HTTP_PORT=' "${ENV_FILE}" | cut -d= -f2-)"
  local bind
  bind="$(grep '^HTTP_BIND=' "${ENV_FILE}" | cut -d= -f2-)"
  cat <<EOF

Demo accounts (tenant tenant-a): reviewer, admin, auditor
Passwords are only in ${ENV_FILE} (mode 600). To read them on this host yourself:

  grep '^DEMO_.*_PASSWORD=' ${ENV_FILE}

The workbench is bound to ${bind:-127.0.0.1}:${port:-80} and is not reachable from the
network until TLS and access protection are enabled (see deploy/README-demo.md).
EOF
}

case "${1:-init}" in
  init) bootstrap ;;
  up) up ;;
  parser) require_docker; write_env; build_parser_image ;;
  credentials) credentials ;;
  *) fail "usage: $0 {init|up|parser|credentials}" ;;
esac
