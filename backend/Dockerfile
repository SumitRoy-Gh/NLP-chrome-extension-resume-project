# Dockerfile
# ----------
# This file builds a Docker image for the Flask backend.
# An image is like a snapshot of a fully configured computer
# with Python, ffmpeg, all packages, and your code — all bundled together.
#
# Docker reads this file top to bottom and executes each instruction.
# Each instruction creates a "layer" — Docker caches layers, so if you
# only change your Python code, it doesn't reinstall all packages again.

# ── Base image ────────────────────────────────────────────────────────────────
# We start from an official Python image. This gives us a clean Linux (Debian)
# system with Python 3.11 already installed.
# "slim" means it's a minimal version — smaller size, faster to download.
FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

# ── Set working directory ─────────────────────────────────────────────────────
# All subsequent commands run inside this folder inside the container.
# If the folder doesn't exist, Docker creates it.
WORKDIR /app

# ── Prevent interactive prompts ──────────────────────────────────────────────
# This tells the Linux package manager to use default values instead of
# stopping the build to ask you questions (like your timezone).
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ── Install system dependencies ───────────────────────────────────────────────
# We need ffmpeg (for audio extraction) and a few libraries that
# Python packages depend on at the system level.
# apt-get is the Linux package manager (like pip but for system tools).
#
# --no-install-recommends: don't install optional extras (keeps image smaller)
# rm -rf /var/lib/apt/lists/*: delete the package list cache after installing
#   (reduces image size — this is a Docker best practice)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# ── Copy requirements first (layer caching trick) ────────────────────────────
# We copy requirements.txt BEFORE copying the rest of the code.
# Why? Docker caches each layer. If we copied all code first, then
# requirements.txt, Docker would reinstall ALL packages every time
# ANY file changed. By copying requirements.txt alone first, Docker
# only reinstalls packages when requirements.txt itself changes.
COPY requirements.txt .

# ── Install Python packages ───────────────────────────────────────────────────
# --no-cache-dir: don't save the download cache inside the image (smaller size)
# torch is installed separately first with the CPU-only version
# because the default torch download is 2GB+ (GPU version we don't need)
RUN pip install --no-cache-dir -r requirements.txt

# ── Pre-download Whisper model ────────────────────────────────────────────────
# Whisper downloads its model weights the first time it runs.
# We pre-download during build so the container starts instantly
# instead of downloading on first request (which would timeout).
# This adds ~150MB to the image but saves startup time.
RUN python -c "import whisper; whisper.load_model('base')"

# ── Pre-download sentence-transformers model ──────────────────────────────────
# Same reason — download the embedding model during build.
# Adds ~90MB to the image.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# ── Pre-download cross-encoder model ─────────────────────────────────────────
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# ── Copy your application code ────────────────────────────────────────────────
# Now we copy the actual Python files. This is done AFTER installing
# packages so that code changes don't trigger a full package reinstall.
COPY app.py .
COPY ingestion.py .
COPY search.py .
COPY chunker.py .

# ── Create directories the app needs ─────────────────────────────────────────
# temp_audio: where yt-dlp saves downloaded audio files
# chroma_store: where ChromaDB saves its database
RUN mkdir -p temp_audio chroma_store

# ── Expose port ───────────────────────────────────────────────────────────────
# Tell Docker that this container listens on port 5000.
# This doesn't publish the port to your computer — that happens in docker-compose.
# It's documentation/metadata for Docker.
EXPOSE 5000

# ── Start command ─────────────────────────────────────────────────────────────
# This is what runs when the container starts.
# We use gunicorn instead of Flask's built-in server because:
# - Flask's built-in server is single-threaded (one request at a time)
# - gunicorn is a production-grade server that handles multiple requests
# - "--timeout 600" allows requests up to 10 minutes (needed for long ingestions)
# - "--workers 1" uses 1 worker (enough for this project, avoids memory issues
#    since each worker loads Whisper + embedding models into RAM)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "600", "--workers", "1", "app:app"]