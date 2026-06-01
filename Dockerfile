# ══════════════════════════════════════════════════════════════════════════════
# BIRDY-EDWARDS — Dockerfile
# Base: Ubuntu 24.04 LTS
# Python: 3.12
# Browser: Playwright Chromium (replaces SeleniumBase + Brave)
# LLM: NVIDIA NIM via OpenCode config
# ══════════════════════════════════════════════════════════════════════════════

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

LABEL maintainer="Jeet Ganguly"
LABEL description="BIRDY-EDWARDS Facebook SOCMINT Platform"
LABEL version="2.0"

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — System packages
# ══════════════════════════════════════════════════════════════════════════════
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python
    python3.12 \
    python3.12-dev \
    python3-pip \
    python3.12-venv \
    # Build tools (required for dlib)
    build-essential \
    cmake \
    g++ \
    make \
    pkg-config \
    # dlib dependencies
    libopenblas-dev \
    liblapack-dev \
    libboost-all-dev \
    libx11-dev \
    libgtk-3-dev \
    libboost-python-dev \
    libboost-thread-dev \
    # Image processing
    libpng-dev \
    libjpeg-dev \
    libtiff-dev \
    libwebp-dev \
    libopencv-dev \
    # Tesseract OCR
    tesseract-ocr \
    tesseract-ocr-ben \
    tesseract-ocr-hin \
    tesseract-ocr-ara \
    tesseract-ocr-urd \
    tesseract-ocr-eng \
    # Playwright system dependencies
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    libpango-1.0-0 \
    libcairo2 \
    fonts-liberation \
    # Utilities
    wget \
    curl \
    unzip \
    git \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — Python virtualenv + packages (except dlib/face_recognition)
# ══════════════════════════════════════════════════════════════════════════════
RUN python3.12 -m venv /app/venv

ENV PATH="/app/venv/bin:$PATH"

RUN pip install --upgrade pip

RUN apt-get update && apt-get install -y python3-tk && rm -rf /var/lib/apt/lists/*

RUN pip install \
    flask \
    playwright \
    Pillow \
    requests \
    pytesseract \
    reportlab \
    networkx \
    pyvis \
    matplotlib \
    seaborn \
    psutil \
    numpy \
    scipy \
    scikit-learn \
    click \
    python-dateutil \
    tqdm \
    opencv-python

# Install Playwright and download Chromium browser
# playwright install-deps runs apt-get internally, so we need the cache available
RUN apt-get update && playwright install-deps chromium && rm -rf /var/lib/apt/lists/*
RUN playwright install chromium

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — dlib (compiled from source)
# ══════════════════════════════════════════════════════════════════════════════
RUN pip install dlib

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — face_recognition (depends on dlib)
# ══════════════════════════════════════════════════════════════════════════════
RUN pip install face_recognition -q
RUN pip install git+https://github.com/ageitgey/face_recognition_models

# ── Patch face_recognition_models for Python 3.12 compatibility ──
RUN python3 - << 'PYEOF'
import sys, os
path = os.path.join(sys.prefix, 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages')
init = os.path.join(path, 'face_recognition_models', '__init__.py')
if not os.path.exists(init):
    print("face_recognition_models not found — skipping patch")
    exit(0)
content = open(init).read()
if 'pkg_resources' not in content:
    print("Already patched — skipping")
    exit(0)
new_content = '''import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
def pose_predictor_model_location():
    return _os.path.join(_here, "models/shape_predictor_68_face_landmarks.dat")
def pose_predictor_five_point_model_location():
    return _os.path.join(_here, "models/shape_predictor_5_face_landmarks.dat")
def face_recognition_model_location():
    return _os.path.join(_here, "models/dlib_face_recognition_resnet_model_v1.dat")
def cnn_face_detector_model_location():
    return _os.path.join(_here, "models/mmod_human_face_detector.dat")
'''
open(init, 'w').write(new_content)
print("Patched:", init)
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 5 — App setup
# ══════════════════════════════════════════════════════════════════════════════
WORKDIR /app

RUN mkdir -p \
    /app/reports \
    /app/face_data \
    /app/post_screenshots \
    /app/status \
    /app/icons

COPY app/ /app/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 6 — Entrypoint
# ══════════════════════════════════════════════════════════════════════════════
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/docker-entrypoint.sh"]
