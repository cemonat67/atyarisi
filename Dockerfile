FROM python:3.11-slim

# Playwright için sistem bağımlılıkları
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright kurulum
RUN pip install playwright --no-cache-dir
RUN playwright install chromium --with-deps || true

COPY backend/ .
COPY frontend/ ./static/

# Data dizini
RUN mkdir -p /app/data

# DB init
RUN python -c "from models.database import init_db; init_db()"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
