FROM node:20-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATUS_DB_PATH=/app/data/status.db \
    STATUS_CHECK_INTERVAL_SECONDS=60

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY main.py ./main.py
COPY --from=frontend-build /frontend/dist ./static

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
