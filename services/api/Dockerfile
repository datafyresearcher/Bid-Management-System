FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The container does not need to be root. It writes only to the storage
# directory, which the operator mounts or points at a volume anyway.
# /data/storage must exist here and be owned by the runtime user: when a
# named volume is first mounted at that path, Docker seeds it with the
# directory's ownership from the image. Without this the volume would be
# root-owned and the API could not write a single document.
RUN useradd --system --uid 10001 --no-create-home bms \
    && mkdir -p /app/storage /data/storage \
    && chown -R bms:bms /app/storage /data/storage
USER bms

EXPOSE 8000
# The health endpoint answers without credentials, so the container runtime
# (and docker-compose) can tell a live API from a started-but-stuck one.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
