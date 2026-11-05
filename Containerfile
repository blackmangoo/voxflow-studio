FROM python:3.10-slim

# Install system dependencies for Playwright and FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
# Add fastAPI and uvicorn if not in requirements
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn pydantic

# Install Playwright browsers (Headless Multi-Threaded Engine)
RUN playwright install chromium
RUN playwright install-deps

# Copy codebase
COPY . .

# Ensure output and temp directories exist
RUN mkdir -p /app/output /app/temp_sound_repo

# Expose the API Port
EXPOSE 8000

# Start the Webhook Server
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
