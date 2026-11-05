# API image: Python 3.12 with uv preinstalled (official Astral image)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Compile .pyc at build time (faster start); copy instead of hardlink (cache mount is another fs);
# use the image's Python instead of downloading one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 1) Dependencies only. This layer is rebuilt only when pyproject.toml or uv.lock change,
#    not on every code change. --frozen: fail if the lock is out of date instead of updating it.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2) The code (.dockerignore keeps .env, .venv and .git out)
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run from the project venv, as a non-root user
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
