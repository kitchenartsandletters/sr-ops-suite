FROM python:3.13-slim

WORKDIR /app

# Install system deps if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy repo
COPY . /app

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

CMD ["sh", "/app/cron/weekly_maintenance/run.sh"]