FROM python:3.12-slim@sha256:2b4f19dae3a777dfc3b76730bda1e82e1f66ab2a2686fa93ca78edbfb4f04ffe

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /release/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      curl \
      tesseract-ocr \
      tesseract-ocr-chi-sim \
      tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints-runtime.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints-runtime.txt

COPY . .

CMD ["sh", "-c", "python manage.py release_check && exec gunicorn zhongbei_info.asgi:application --bind 0.0.0.0:8000 --workers 1 -k uvicorn_worker.UvicornWorker --timeout 60"]
