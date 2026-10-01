FROM python:3.11-slim

# Tesseract OCR binary — this is the one dependency that can't come from pip.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# run_engine.py serves HTTPS with a required client certificate when
# /app/certs exists (mount the output of scripts/make_tls_certs.py there) and
# refuses to listen on a public address without it.
EXPOSE 8000
CMD ["python", "run_engine.py", "--host", "0.0.0.0", "--port", "8000"]
