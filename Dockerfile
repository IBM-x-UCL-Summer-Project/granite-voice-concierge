FROM python:3.12-slim AS application

ARG APP_UID=10001
ARG APP_GID=10001

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

# Copy project metadata before source so dependency installation remains cached
# across normal application edits.
COPY pyproject.toml requirements.txt requirements-dev.txt ./

# Install CPU-only PyTorch first. The default Linux wheels may pull several
# gigabytes of CUDA libraries that this image cannot use.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchaudio \
    && python -c 'import subprocess, sys, tomllib; dependencies = tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]; subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *dependencies])'

# Keep the selected Piper voice in its own cached layer. Changing the voice
# rebuilds only this inexpensive model layer, not the Python dependencies.
ARG PIPER_VOICE=en_GB-alan-medium
RUN mkdir -p src/voice_concierge/voice_output \
    && python -m piper.download_voices \
        --download-dir src/voice_concierge/voice_output \
        "${PIPER_VOICE}"

# Source changes should not invalidate the expensive dependency layer.
COPY src ./src

RUN pip install --no-cache-dir --no-deps -e .

# Static UI changes should not invalidate the Python dependency layer.
COPY web ./web

# Run the application without root privileges. APP_UID and APP_GID can be set
# to the host user's IDs on native Linux bind-mount deployments.
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
        --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
    && mkdir -p .local/memory .local/preferences .local/reminders .local/logs \
        /home/app/.cache \
    && chown -R app:app .local /home/app

# Normalize inside the Linux image as well as enforcing LF through
# .gitattributes. Existing Windows worktrees can retain a CRLF copy of an
# unchanged script after pulling the attributes file for the first time.
COPY entrypoint.sh /usr/local/bin/
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

ENV HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache

USER app

# Browser UI/API and binary browser microphone stream
EXPOSE 4173 4174

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Bind inside the container; host exposure remains controlled by the published
# port address in Compose or docker run.
CMD ["python", "-m", "voice_concierge.app.web", "--host", "0.0.0.0", "--port", "4173", "--audio-stream-port", "4174", "--voice-io", "--log-level", "INFO"]

# Development and test tooling live in a separate target. The final runtime
# stage below remains small, while docker-compose.dev.yml can opt into this
# target when tests or source-mounted development are requested.
FROM application AS test

USER root
RUN python -c 'import subprocess, sys, tomllib; dependencies = tomllib.load(open("pyproject.toml", "rb"))["project"]["optional-dependencies"]["dev"]; subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *dependencies])'
COPY benchmarks ./benchmarks
COPY docs ./docs
COPY tests ./tests
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"
USER app
CMD ["python", "-m", "pytest", "-v"]

FROM application AS runtime
