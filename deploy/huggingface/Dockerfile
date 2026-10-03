# Screening engine for a Hugging Face Space (Docker SDK, free CPU hardware).
# Hugging Face serves the Space over HTTPS and forwards to port 7860 inside the
# container, so the engine itself listens on plain HTTP there; every /api call
# still has to carry the engine API key (Space secret ENGINE_API_KEY).
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-nep \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as user 1000.
RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
# CPU build of PyTorch: the free hardware has no GPU, and the CUDA build is several GB.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
RUN mkdir -p uploads && chown -R user /app
USER user

ENV ENGINE_ALLOW_PLAINTEXT=true \
    LOCALIZATION_DEVICE=cpu \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["python", "run_engine.py", "--host", "0.0.0.0", "--port", "7860"]
