FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (curl and ffmpeg for audio/video streaming)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose dynamic port
ENV PORT=8000
EXPOSE 8000

# Start FastAPI Uvicorn server with dynamic port support
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
