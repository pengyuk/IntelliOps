FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ src/
COPY data/ data/

# Create data dir for SQLite
RUN mkdir -p /app/data

EXPOSE 8000

ENV INTELLIOPS_DB=/app/data/intelliops.db
ENV LLM_PROVIDER=none

CMD ["uvicorn", "src.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
