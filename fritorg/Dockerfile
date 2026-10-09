# Fritorg – production image. Build from this folder: docker build -t fritorg .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY fritorg ./fritorg
RUN pip install . \
    && useradd --create-home --uid 10001 fritorg \
    && mkdir -p /data /uploads \
    && chown fritorg:fritorg /data /uploads

USER fritorg
# The app sits behind a reverse proxy (Caddy in deploy/docker-compose.yml) that sets
# X-Forwarded-For; the container port must not be exposed to the internet directly.
ENV FRITORG_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000 \
    FORWARDED_ALLOW_IPS=*
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["fritorg", "serve"]
