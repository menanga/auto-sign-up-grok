FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    CHROME_BIN=/usr/bin/chromium

# system deps for Chromium, Xvfb, and Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-common \
    xvfb \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libgtk-3-0 \
    fonts-liberation \
    fonts-noto-color-emoji \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser + runtime deps
RUN playwright install chromium \
    && playwright install-deps chromium

COPY . .

# Default: run forever, auto-add success accounts to 9router
CMD ["xvfb-run", "-a", "python", "grok-signup-nodriver.py", "--auto-add"]
