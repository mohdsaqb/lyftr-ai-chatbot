FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --no-compile -r requirements.txt

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UVICORN_HOST=0.0.0.0 UVICORN_PORT=8000
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app"]
