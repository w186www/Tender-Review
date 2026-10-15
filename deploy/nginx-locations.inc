# Shared routing rules for the workbench and the API. Included by both the plain HTTP
# server and the TLS overlay so the two can never drift apart.

root /usr/share/nginx/html;
index index.html;

add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options DENY always;
add_header Referrer-Policy same-origin always;
add_header Content-Security-Policy "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'" always;

gzip on;
gzip_min_length 1024;
gzip_types text/css application/javascript application/json image/svg+xml;

# Hashed assets are immutable; index.html must never be cached or the SPA would keep
# loading a deleted bundle after an update.
location /assets/ {
    expires 30d;
    add_header Cache-Control "public, immutable";
    try_files $uri =404;
}

location = /index.html {
    add_header Cache-Control "no-store";
}

# The application has no login throttling of its own (see the security section of
# deploy/README-demo.md), so the reverse proxy carries it: the token endpoint is the one
# path where an attacker can guess credentials, and it is limited per client address.
# limit_req_zone itself lives in the http context of the active server config file.
location = /api/v1/auth/token {
    limit_req zone=loginzone burst=6 nodelay;
    limit_req_status 429;

    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_read_timeout 60s;
}

location /api/ {
    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    # Review runs execute inside the API process and can exceed a minute.
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    # Stream uploads and report downloads instead of buffering them whole.
    proxy_request_buffering off;
    proxy_buffering off;
}

# React Router routes resolve client-side.
location / {
    try_files $uri $uri/ /index.html;
}
