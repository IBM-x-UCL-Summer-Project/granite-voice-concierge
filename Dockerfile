FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    portaudio19-dev \
    libsndfile1 \
    libasound2-dev \
    libsqlite3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml requirements.txt requirements-dev.txt ./
COPY src ./src

# Install CPU-only PyTorch first. The default Linux wheels may pull several
# gigabytes of CUDA libraries that this image cannot use.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchaudio \
    && pip install --no-cache-dir -e .

# Static UI changes should not invalidate the Python dependency layer.
COPY web ./web

# Create persistent data directories
RUN mkdir -p .local/memory .local/preferences .local/reminders .local/logs

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Browser UI and API
EXPOSE 4173

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Default to web UI, can override with live
CMD ["python", "-m", "voice_concierge.app.web", "--voice-io", "--log-level", "DEBUG"]
