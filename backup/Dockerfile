# Stage 1: Builder - download rclone static binary
FROM alpine:3.21 AS builder

WORKDIR /tmp

# Detect architecture and download appropriate rclone binary
RUN apk add --no-cache curl unzip && \
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then \
        RCLONE_ARCH="arm64"; \
    elif [ "$ARCH" = "x86_64" ]; then \
        RCLONE_ARCH="amd64"; \
    else \
        RCLONE_ARCH="arm"; \
    fi && \
    echo "Downloading rclone for architecture: $RCLONE_ARCH" && \
    curl -o rclone.zip "https://downloads.rclone.org/rclone-current-linux-${RCLONE_ARCH}.zip" && \
    unzip rclone.zip && \
    mv rclone-*-linux-${RCLONE_ARCH}/rclone /tmp/rclone && \
    chmod +x /tmp/rclone

# Stage 2: Final image with Python runtime
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies including sqlite3 and rclone dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    sqlite3 \
    gnupg \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy rclone static binary
COPY --from=builder /tmp/rclone /usr/bin/rclone

# Install Python dependencies
COPY backup/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create backup working directory and empty default rclone config
RUN mkdir -p /backups /config/rclone && \
    touch /config/rclone/rclone.conf

# Copy application
COPY backup/backup.py .
COPY backup/restore.py .

CMD ["python", "-u", "backup.py"]
