# The PyPI torch wheel that openai-whisper pulls in bundles CUDA 13.0; the host needs NVIDIA driver 580+.
FROM nvidia/cuda:13.0.2-runtime-ubuntu24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra whisper --no-install-project

COPY src ./src
RUN uv sync --frozen --extra whisper
COPY tests ./tests

ENV PATH=/opt/venv/bin:$PATH \
    TRANSCRIBE_DATA_DIR=/data

EXPOSE 3002
VOLUME /data

CMD ["transcribe"]
