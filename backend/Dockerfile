FROM python:3.12-slim

WORKDIR /app

# System deps for Playwright & PDF tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg libglib2.0-0 libnss3 libx11-xcb1 libxcomposite1 \
    libxrandr2 libxdamage1 libxext6 libxfixes3 libpango-1.0-0 \
    libcairo2 libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libgbm1 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium && playwright install-deps chromium

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
