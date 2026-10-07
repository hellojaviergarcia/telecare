# Stage 1: build
FROM cgr.dev/chainguard/python:latest-dev AS builder

WORKDIR /app

COPY requirements.txt .
RUN python -m venv /app/venv && /app/venv/bin/pip install --no-cache-dir -r requirements.txt


# Stage 2: runtime
FROM cgr.dev/chainguard/python:latest

WORKDIR /app

COPY --from=builder /app/venv /app/venv
COPY app/ ./app/
COPY run.py .

ENV PATH="/app/venv/bin:$PATH"

EXPOSE 8000

ENTRYPOINT ["python", "run.py"]
