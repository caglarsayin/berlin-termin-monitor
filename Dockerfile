# Headless Berlin Termin Monitor for a Linux server (x86_64).
# Runtime data (config, slot history, browser profile, logs) lives in /data.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TERMIN_DATA_DIR=/data \
    TZ=Europe/Berlin

# Google Chrome (the app launches channel="chrome") plus its system libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && pip install --no-cache-dir playwright==1.64.1 \
    && playwright install --with-deps chrome \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 termin \
    && mkdir -p /data && chown termin:termin /data

WORKDIR /app
COPY termin_monitor.py ./
COPY termin ./termin

USER termin
VOLUME ["/data"]

ENTRYPOINT ["python", "termin_monitor.py"]
CMD ["--between", "17:00-20:00", "--days", "14"]
