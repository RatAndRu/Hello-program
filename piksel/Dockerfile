# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm AS site
WORKDIR /site
COPY piksel/web /site/
COPY piksel/examples /site/examples
# bust cache 42afdec
# статический Nginx — как forma/showcase/Dockerfile
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY piksel/nginx.conf /etc/nginx/nginx.conf
COPY --from=site /site /usr/share/nginx/html/
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8000/healthz || exit 1
