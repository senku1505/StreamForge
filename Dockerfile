FROM python:3.9-slim

# Install Redis, FFmpeg, and build tools
RUN apt-get update && apt-get install -y \
    redis-server \
    ffmpeg \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set up user 1000 for Hugging Face Spaces compatibility
RUN useradd -m -u 1000 user
WORKDIR /app

# Cache packages
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy source files and set ownership to user 1000
COPY --chown=user:user . /app/

# Create media/static dirs and set permissions (required for local storage mode if used)
RUN mkdir -p /app/media /app/static && chown -R user:user /app

# Switch to the non-root user
USER user

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

# Expose the default Hugging Face Space port
EXPOSE 7860

# Start script
CMD ["/app/start.sh"]
