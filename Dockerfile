FROM python:3.9-slim

# Install FFmpeg and build tools
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache packages
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . /app/

EXPOSE 8000
