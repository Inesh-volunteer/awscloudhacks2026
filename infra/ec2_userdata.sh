#!/bin/bash
# AutoRedTeam — EC2 user-data script for DVWA target instance
# Installs Docker and starts DVWA on port 80.
# Tested on Amazon Linux 2023 / Ubuntu 22.04.

set -euo pipefail

LOG_FILE="/var/log/dvwa_setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting DVWA setup..."

# ---------------------------------------------------------------------------
# Detect OS and install Docker
# ---------------------------------------------------------------------------
if command -v dnf &>/dev/null; then
    # Amazon Linux 2023 / RHEL
    dnf update -y
    dnf install -y docker
    systemctl enable docker
    systemctl start docker
elif command -v apt-get &>/dev/null; then
    # Ubuntu / Debian
    apt-get update -y
    apt-get install -y docker.io
    systemctl enable docker
    systemctl start docker
else
    echo "ERROR: Unsupported OS — cannot install Docker"
    exit 1
fi

# Add ec2-user / ubuntu to docker group
if id ec2-user &>/dev/null; then
    usermod -aG docker ec2-user
elif id ubuntu &>/dev/null; then
    usermod -aG docker ubuntu
fi

# ---------------------------------------------------------------------------
# Pull and start DVWA
# ---------------------------------------------------------------------------
DVWA_IMAGE="vulnerables/web-dvwa:latest"
DVWA_CONTAINER="dvwa"
DVWA_PORT=80

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pulling DVWA image: $DVWA_IMAGE"
docker pull "$DVWA_IMAGE"

# Remove any existing container
docker rm -f "$DVWA_CONTAINER" 2>/dev/null || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting DVWA container on port $DVWA_PORT"
docker run -d \
    --name "$DVWA_CONTAINER" \
    --restart unless-stopped \
    -p "${DVWA_PORT}:80" \
    -e "MYSQL_PASS=dvwa" \
    "$DVWA_IMAGE"

# ---------------------------------------------------------------------------
# Wait for DVWA to become healthy
# ---------------------------------------------------------------------------
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Waiting for DVWA to become healthy..."
MAX_WAIT=120
ELAPSED=0
until curl -sf "http://localhost:${DVWA_PORT}/login.php" > /dev/null 2>&1; do
    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
        echo "ERROR: DVWA did not become healthy within ${MAX_WAIT}s"
        docker logs "$DVWA_CONTAINER"
        exit 1
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] DVWA is healthy at http://localhost:${DVWA_PORT}"

# ---------------------------------------------------------------------------
# Initialize DVWA database via setup.php
# ---------------------------------------------------------------------------
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Initializing DVWA database..."
curl -sf "http://localhost:${DVWA_PORT}/setup.php" \
    -d "create_db=Create+%2F+Reset+Database" \
    -c /tmp/dvwa_cookies.txt \
    -b /tmp/dvwa_cookies.txt \
    -L || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] DVWA setup complete."

# ---------------------------------------------------------------------------
# Install CloudWatch agent for container logs (optional)
# ---------------------------------------------------------------------------
if command -v dnf &>/dev/null; then
    dnf install -y amazon-cloudwatch-agent || true
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] EC2 DVWA setup finished successfully."
