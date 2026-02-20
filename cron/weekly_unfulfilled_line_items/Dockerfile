# cron/weekly_unfulfilled_line_items/Dockerfile

FROM python:3.12-slim

# Set working directory inside container
WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy entire repo into container
COPY ../../ /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Ensure scripts are executable
RUN chmod +x cron/weekly_unfulfilled_line_items/run.sh

# Run via shell script
CMD ["bash", "cron/weekly_unfulfilled_line_items/run.sh"]