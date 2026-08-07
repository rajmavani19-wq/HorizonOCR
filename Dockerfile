# Private HorizonOCR production container
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    PORT=8080 \
    DATA_DIR=/var/lib/horizonocr \
    HF_HOME=/var/lib/horizonocr/models/huggingface_hub \
    TRANSFORMERS_CACHE=/var/lib/horizonocr/models/transformers \
    HUGGINGFACE_HUB_CACHE=/var/lib/horizonocr/models/huggingface_hub \
    TORCH_HOME=/var/lib/horizonocr/models/torch \
    EASYOCR_MODULE_PATH=/var/lib/horizonocr/models/easyocr

# Minimal native dependencies for PDF processing and the English OCR fallback.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /var/lib/horizonocr/models \
    && chown -R appuser:appuser /app /var/lib/horizonocr

USER appuser
VOLUME ["/var/lib/horizonocr"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

CMD ["gunicorn", "--config", "gunicorn.conf.py", "server:app"]
