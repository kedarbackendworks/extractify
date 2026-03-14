#!/usr/bin/env bash
# ============================================================
# Extractify Backend – Startup Script
#
# 1. Start the bgutil PO Token server (YouTube anti-bot bypass)
# 2. Wait for the server to be ready
# 3. Start the FastAPI application
# ============================================================

set -e

echo "[start.sh] Starting bgutil PO Token server on port 4416..."
node /opt/bgutil/server/build/main.js &
BGUTIL_PID=$!

# Give the Node.js server time to initialise
sleep 3

# Verify bgutil server is running
if kill -0 $BGUTIL_PID 2>/dev/null; then
    echo "[start.sh] bgutil PO Token server started (PID=$BGUTIL_PID)"
else
    echo "[start.sh] WARNING: bgutil server failed to start — YouTube extraction may fail"
fi

echo "[start.sh] Starting FastAPI (uvicorn) on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
