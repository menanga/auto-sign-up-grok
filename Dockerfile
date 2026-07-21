FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# Install system dependencies for Playwright Chrome
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    xvfb \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    fonts-liberation \
    fonts-noto-color-emoji \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chrome (bundled, no system Chrome needed)
RUN playwright install chrome \
    && playwright install-deps chrome

# Copy application files
COPY . .

# Default: run with Xvfb, auto-add to 9Router
CMD ["xvfb-run", "-a", "python", "grok-signup-playwright-gmail.py", "--auto-add"]
