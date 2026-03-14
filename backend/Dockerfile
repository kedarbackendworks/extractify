# ============================================================
# Stage 1: builder – install Python deps in an isolated layer
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# System headers only needed for compiling C-extension wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# Stage 2: runtime – lean image with only what we need
# ============================================================
FROM python:3.12-slim

# Prevent .pyc files and enable real-time log output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Runtime system deps for Playwright Chromium, PDF tools, and ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg libglib2.0-0 libnss3 libx11-xcb1 libxcomposite1 \
    libxrandr2 libxdamage1 libxext6 libxfixes3 libpango-1.0-0 \
    libcairo2 libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libgbm1 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install Node.js 22 LTS (required for bgutil PO Token server)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs git && \
    rm -rf /var/lib/apt/lists/*

# Build bgutil PO Token server (YouTube anti-bot bypass)
# 1. Clone the provider repo + build the Node.js server
# 2. Install the yt-dlp plugin via pip
RUN git clone --single-branch --branch 1.3.1 \
      https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil && \
    cd /opt/bgutil/server && npm ci && npx tsc && \
    pip install --no-cache-dir bgutil-ytdlp-pot-provider && \
    chmod -R o+rx /opt/bgutil

# Copy pre-built Python packages from builder stage
COPY --from=builder /install /usr/local

# Install Playwright Chromium to a shared path accessible by the non-root user.
# We skip `playwright install-deps` because it references obsolete font packages on Debian Trixie.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium && \
    chmod -R o+rx /ms-playwright

# Create a non-root user for security
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# Use shell form so $PORT (injected by Render / Railway / etc.) is expanded at runtime.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
