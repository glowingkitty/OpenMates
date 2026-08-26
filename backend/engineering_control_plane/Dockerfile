FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/engineering_control_plane/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/engineering_control_plane ./backend/engineering_control_plane

EXPOSE 8000

CMD ["python", "-m", "backend.engineering_control_plane.entrypoint"]
