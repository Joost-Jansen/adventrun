FROM python:3.13-slim
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Amsterdam
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app/ app/
RUN useradd --uid 1000 --create-home appuser
USER appuser
EXPOSE 8000
# HOST 0.0.0.0, not :: (otherwise the IPv4 healthcheck on Railway fails).
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host \"${HOST:-0.0.0.0}\" --port \"${PORT:-8000}\" --no-proxy-headers --no-server-header"]
