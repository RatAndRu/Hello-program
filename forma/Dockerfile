# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ARG FORMA_REVISION=local
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/forma \
    FORMA_DATA=/app/data \
    FORMA_DEMO=1 \
    FORMA_START_PROJECT=train_carriage \
    FORMA_REVISION=${FORMA_REVISION}

WORKDIR /app
COPY forma/requirements.txt /tmp/forma-requirements.txt
RUN pip install --no-cache-dir -r /tmp/forma-requirements.txt \
    && rm -f /tmp/forma-requirements.txt

COPY forma/ /app/forma/
RUN groupadd --system forma \
    && useradd --system --gid forma --home-dir /app --shell /usr/sbin/nologin forma \
    && mkdir -p /app/data/projects \
    && cp /app/forma/examples/train_carriage.forma /app/data/projects/train_carriage.forma \
    && cp /app/forma/examples/living_room_diorama.forma /app/data/projects/living_room_diorama.forma \
    && printf '%s' '{"name":"Плацкартный вагон 61-4194 — 1:20"}' \
        > /app/data/projects/train_carriage.json \
    && printf '%s' '{"name":"Гостиная 1:20 — готовая диорамма"}' \
        > /app/data/projects/living_room_diorama.json \
    && chown -R forma:forma /app

USER forma
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()" || exit 1

CMD ["python", "/app/forma/run_forma.py", "--host", "0.0.0.0", "--port", "8000", "--no-open"]
