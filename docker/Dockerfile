# The capture pipeline, packaged to run unattended on a NAS or any small server.
# Build from the repository root:  docker build -f docker/Dockerfile -t nightshift .
FROM python:3.12-slim

# Without this, the published package has no link back to the code that built
# it, and the only way to read the Dockerfile is to already know the repo.
LABEL org.opencontainers.image.source="https://github.com/martinbouvet2000-tech/nightshift" \
      org.opencontainers.image.description="nightshift capture pipeline" \
      org.opencontainers.image.licenses="MIT"

# yt-dlp needs no system package; ffmpeg is only required when you enable the
# whisper extra, which this image deliberately leaves out — it would pull in
# torch and multiply the image size for a feature most deployments never use.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIGHTSHIFT_VAULT=/vault \
    NIGHTSHIFT_CONFIG=/config/nightshift.yaml \
    TZ=Europe/Paris

WORKDIR /app
COPY pipeline/ /app/pipeline/
RUN pip install --no-cache-dir "./pipeline[youtube]"

# Run as a normal user. The vault is mounted from the host, so the container
# must not be able to write to it as root and leave files nobody can edit.
RUN useradd --create-home --uid 1000 nightshift \
    && mkdir -p /vault /config \
    && chown -R nightshift:nightshift /vault /config
USER nightshift

# Fails while the config is missing or the vault is unreachable, which is what
# a NAS dashboard should show instead of a container that looks healthy and
# quietly does nothing.
HEALTHCHECK --interval=5m --timeout=30s --start-period=20s --retries=2 \
    CMD nightshift health || exit 1

# Twice a day by default; override with the command in docker-compose.yml.
ENTRYPOINT ["python", "-m", "nightshift.schedule"]
CMD ["--at", "09:00,21:00", "--", "nightshift", "run"]
