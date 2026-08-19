FROM python:3.12-slim AS application

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

# Install CPU-only PyTorch first. The default Linux wheels may pull several
# gigabytes of CUDA libraries that this image cannot use.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchaudio \
    && python -c 'import subprocess, sys, tomllib; dependencies = tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]; subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *dependencies])'

# Source changes should not invalidate the expensive dependency layer.
COPY src ./src

# Keep the Piper voice assets in the image without transferring them through
# the macOS build context. Piper requires both the model and its companion
# configuration file, so download and verify both as one cached layer.
RUN curl --fail --location --retry 3 \
        --output src/voice_concierge/voice_output/en_GB-alan-medium.onnx \
        https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx \
    && echo "0a309668932205e762801f1efc2736cd4b0120329622adf62be09e56339d3330  src/voice_concierge/voice_output/en_GB-alan-medium.onnx" \
        | sha256sum --check --strict \
    && curl --fail --location --retry 3 \
        --output src/voice_concierge/voice_output/en_GB-alan-medium.onnx.json \
        https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json \
    && echo "c0f0d124e5895c00e7c03b35dcc8287f319a6998a365b182deb5c8e752ee8c1e  src/voice_concierge/voice_output/en_GB-alan-medium.onnx.json" \
        | sha256sum --check --strict

RUN pip install --no-cache-dir --no-deps -e .

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

# Development and test tooling live in a separate target. The final runtime
# stage below remains small, while docker-compose.dev.yml can opt into this
# target when tests or source-mounted development are requested.
FROM application AS test

RUN python -c 'import subprocess, sys, tomllib; dependencies = tomllib.load(open("pyproject.toml", "rb"))["project"]["optional-dependencies"]["dev"]; subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *dependencies])'
COPY tests ./tests
CMD ["python", "-m", "pytest", "-v"]

FROM application AS runtime
