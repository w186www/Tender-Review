#!/usr/bin/env bash
# Certificate lifecycle for the public-IP deployment.
#
#   ./deploy/certbot.sh issue-staging   request a staging certificate (quota-safe rehearsal)
#   ./deploy/certbot.sh issue           request the production certificate
#   ./deploy/certbot.sh deploy          install the current cert into ./certs and reload nginx
#   ./deploy/certbot.sh renew           renew when due, then deploy (what the timer runs)
#   ./deploy/certbot.sh status          print validity, renewal threshold and alert state
#   ./deploy/certbot.sh check-expiry    exit non-zero and raise a marker when close to expiry
#
# Why this exists rather than plain `certbot renew`:
#   * Let's Encrypt IP certificates are short-lived (160 hours / ~6 days) and the same IP is
#     limited to 5 certificates per 7 days. The 2 day renewal threshold below yields roughly
#     1.5 renewals per week, far inside that limit, while an unconditional daily renewal
#     would exhaust the quota.
#   * Certbot can obtain IP certificates but cannot install them, and its live/ entries are
#     symlinks into archive/. This script copies real bytes and swaps them atomically.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/deploy/.env"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${REPO_ROOT}/docker-compose.demo.yml")

CERT_NAME="${CERT_NAME:-tender-review-ip}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot:v5.8.0}"
CERTBOT_DIR="${REPO_ROOT}/certbot/conf"
CERTS_DIR="${TLS_CERT_DIR:-${REPO_ROOT}/certs}"
LIVE_DIR="/etc/letsencrypt/live/${CERT_NAME}"
LOG_FILE="${REPO_ROOT}/certbot/renew.log"
LOCK_FILE="${REPO_ROOT}/certbot/.lock"
ALERT_MARKER="${REPO_ROOT}/certbot/EXPIRING"
ALERT_HOURS="${ALERT_HOURS:-48}"

mkdir -p "${REPO_ROOT}/certbot" "${CERTS_DIR}" "${REPO_ROOT}/acme-webroot"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}" >&2; }
fail() { log "ERROR: $*"; exit 1; }

load_env() {
  [ -f "${ENV_FILE}" ] || fail "missing ${ENV_FILE}; run ./deploy/bootstrap.sh init first"
  # shellcheck disable=SC1090
  set -a; . "${ENV_FILE}"; set +a
  PUBLIC_IP="${PUBLIC_IP:-}"
  [ -n "${PUBLIC_IP}" ] || fail "set PUBLIC_IP in ${ENV_FILE} to the address the certificate is issued for"
}

certbot_run() {
  docker run --rm \
    -v "${CERTBOT_DIR}:/etc/letsencrypt" \
    -v "${REPO_ROOT}/acme-webroot:/var/www/acme" \
    "${CERTBOT_IMAGE}" "$@"
}

fingerprint_deployed() {
  [ -f "${CERTS_DIR}/fullchain.pem" ] || { echo none; return 0; }
  sha256sum "${CERTS_DIR}/fullchain.pem" | awk '{print $1}'
}

# Reads through certbot's live/ symlink on purpose: the hash of the certificate certbot
# currently holds, which is what tells us whether anything actually changed.
fingerprint_issued() {
  docker run --rm -v "${CERTBOT_DIR}:/etc/letsencrypt:ro" \
    --entrypoint sha256sum "${CERTBOT_IMAGE}" "${LIVE_DIR}/fullchain.pem" 2>/dev/null \
    | awk '{print $1}' || echo none
}

# Certbot stores live/<name>/{fullchain,privkey}.pem as symlinks into archive/. Copying the
# bytes with -L yields a directory of ordinary files, which is also what makes the per-file
# rename below atomic for nginx.
install_certificate() {
  mkdir -p "${CERTS_DIR}/.previous"
  docker run --rm \
    -v "${CERTBOT_DIR}:/etc/letsencrypt:ro" \
    -v "${CERTS_DIR}:/out" \
    --entrypoint sh "${CERTBOT_IMAGE}" -c "
      set -e
      if [ ! -e '${LIVE_DIR}/fullchain.pem' ]; then echo 'no certificate at ${LIVE_DIR}' >&2; exit 1; fi
      cp -L '${LIVE_DIR}/fullchain.pem' /out/.fullchain.pem.tmp
      cp -L '${LIVE_DIR}/privkey.pem'   /out/.privkey.pem.tmp
      chmod 644 /out/.fullchain.pem.tmp
      chmod 600 /out/.privkey.pem.tmp
      # Refuse to publish a rehearsal certificate. Installing one from the staging CA would
      # look like a successful deployment while every browser rejects it.
      if openssl x509 -in /out/.fullchain.pem.tmp -noout -issuer 2>/dev/null | grep -qi 'STAGING'; then
        if [ \"${ALLOW_STAGING_CERT:-0}\" != '1' ]; then
          rm -f /out/.fullchain.pem.tmp /out/.privkey.pem.tmp
          echo 'refusing to deploy a staging certificate (set ALLOW_STAGING_CERT=1 to override)' >&2
          exit 1
        fi
      fi
    "
  if [ -f "${CERTS_DIR}/fullchain.pem" ]; then
    cp -p "${CERTS_DIR}/fullchain.pem" "${CERTS_DIR}/.previous/fullchain.pem"
    cp -p "${CERTS_DIR}/privkey.pem" "${CERTS_DIR}/.previous/privkey.pem"
  fi
  # rename(2) inside one directory is atomic, so nginx never observes a partial file.
  mv -f "${CERTS_DIR}/.fullchain.pem.tmp" "${CERTS_DIR}/fullchain.pem"
  mv -f "${CERTS_DIR}/.privkey.pem.tmp" "${CERTS_DIR}/privkey.pem"
}

nginx_test() {
  "${COMPOSE[@]}" exec -T nginx nginx -t >/dev/null 2>&1
}

# Verify first, reload second, and restore the previous pair when verification fails.
activate() {
  if ! nginx_test; then
    log "nginx -t rejected the new certificate; rolling back"
    if [ -f "${CERTS_DIR}/.previous/fullchain.pem" ]; then
      mv -f "${CERTS_DIR}/.previous/fullchain.pem" "${CERTS_DIR}/fullchain.pem"
      mv -f "${CERTS_DIR}/.previous/privkey.pem" "${CERTS_DIR}/privkey.pem"
      if nginx_test; then
        log "rollback verified; the previously working certificate is still in place"
      else
        log "WARNING: the restored certificate also failed nginx -t"
      fi
    else
      log "no previous certificate to restore"
    fi
    fail "certificate activation aborted"
  fi
  log "nginx -t passed"
  if "${COMPOSE[@]}" exec -T nginx nginx -s reload >/dev/null 2>&1; then
    log "nginx reloaded"
  else
    fail "nginx reload failed"
  fi
}

deployed_not_after() {
  [ -f "${CERTS_DIR}/fullchain.pem" ] || return 1
  openssl x509 -enddate -noout -in "${CERTS_DIR}/fullchain.pem" 2>/dev/null | sed 's/^notAfter=//'
}

deployed_remaining_hours() {
  local not_after end now
  not_after="$(deployed_not_after)" || return 1
  [ -n "${not_after}" ] || return 1
  end="$(date -u -d "${not_after}" +%s 2>/dev/null)" || return 1
  now="$(date -u +%s)"
  echo $(( (end - now) / 3600 ))
}

main="${1:-}"
case "${main}" in
  issue-staging|issue)
    load_env
    staging=()
    force=()
    if [ "${main}" = "issue-staging" ]; then
      staging=(--staging)
    else
      # `certbot certonly` declines to reissue while an existing certificate is "not yet due
      # for renewal", which silently kept the staging certificate in place during the first
      # attempt. An explicit issuance must actually issue.
      force=(--force-renewal)
    fi
    email_args=(--register-unsafely-without-email)
    if [ -n "${ACME_EMAIL:-}" ]; then
      email_args=(--email "${ACME_EMAIL}")
    fi
    log "requesting ${main} certificate for IP ${PUBLIC_IP} (profile shortlived)"
    certbot_run certonly --webroot -w /var/www/acme \
      --cert-name "${CERT_NAME}" \
      --ip-address "${PUBLIC_IP}" \
      --preferred-profile shortlived \
      --agree-tos --no-eff-email "${email_args[@]}" \
      --non-interactive "${staging[@]}" "${force[@]}"
    renewal_conf="${CERTBOT_DIR}/renewal/${CERT_NAME}.conf"
    if [ -f "${renewal_conf}" ]; then
      if grep -q '^renew_before_expiry' "${renewal_conf}"; then
        sed -i 's/^renew_before_expiry.*/renew_before_expiry = 2 days/' "${renewal_conf}"
      else
        printf 'renew_before_expiry = 2 days\n' >> "${renewal_conf}"
      fi
      log "renewal threshold set to 2 days in $(basename "${renewal_conf}")"
    fi
    if [ "${main}" = "issue" ]; then
      install_certificate
      activate
    fi
    log "${main} finished"
    ;;

  deploy)
    load_env
    install_certificate
    activate
    ;;

  renew)
    load_env
    # One renewal at a time; two overlapping runs could both drive an ACME order.
    exec 9>"${LOCK_FILE}"
    if ! flock -n 9; then
      log "another renewal is already running; exiting"
      exit 0
    fi
    before="$(fingerprint_deployed)"
    log "renewal check starting (deployed certificate: ${before:0:16})"
    certbot_run renew --non-interactive
    issued="$(fingerprint_issued)"
    if [ "${issued}" = "none" ]; then
      fail "no certificate found after renew; inspect the log above"
    fi
    if [ "${issued}" = "${before}" ]; then
      log "no renewal was due"
    else
      install_certificate
      activate
      rm -f "${ALERT_MARKER}"
      log "renewed and activated; remaining $(deployed_remaining_hours)h"
    fi
    ;;

  status)
    load_env
    echo "certificate : ${CERT_NAME}"
    echo "public ip   : ${PUBLIC_IP}"
    echo "not after   : $(deployed_not_after || echo none)"
    echo "remaining   : $(deployed_remaining_hours || echo unknown) hours"
    echo "alert below : ${ALERT_HOURS} hours"
    if [ -f "${ALERT_MARKER}" ]; then
      echo "alert state : EXPIRING marker present"
    else
      echo "alert state : ok"
    fi
    echo "--- certbot view ---"
    certbot_run certificates 2>/dev/null || true
    ;;

  check-expiry)
    if ! remaining="$(deployed_remaining_hours)"; then
      log "ERROR: no deployed certificate to inspect"
      exit 2
    fi
    if [ "${remaining}" -lt "${ALERT_HOURS}" ]; then
      printf '%s\n' "deployed certificate expires in ${remaining}h (<${ALERT_HOURS}h)" > "${ALERT_MARKER}"
      log "ALERT: certificate expires in ${remaining}h; renewal is overdue"
      exit 1
    fi
    rm -f "${ALERT_MARKER}"
    log "certificate healthy: ${remaining}h remaining"
    ;;

  *)
    printf 'usage: %s {issue-staging|issue|deploy|renew|status|check-expiry}\n' "$0" >&2
    exit 2
    ;;
esac
