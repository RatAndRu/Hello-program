# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm AS assets

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/src/forma
WORKDIR /src
COPY forma/requirements.txt /tmp/forma-requirements.txt
RUN pip install --no-cache-dir -r /tmp/forma-requirements.txt Pillow \
    && rm -f /tmp/forma-requirements.txt
COPY forma/ /src/forma/
ARG FORMA_REVISION=local
RUN python /src/forma/showcase/build_showcase.py \
    --repo-root /src --output /site --revision "${FORMA_REVISION}"

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY forma/showcase/nginx.conf /etc/nginx/nginx.conf
COPY --from=assets /site/ /usr/share/nginx/html/
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8000/healthz || exit 1
