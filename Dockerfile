FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOGHOUSE_CONFIG=/app/config/local.yaml

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN python -m pip install --no-cache-dir . \
    && rm -rf /app/build /app/src/*.egg-info

EXPOSE 18793

# API containers should run this default or override explicitly with:
#   ["doghouse", "serve"]
# Worker/scheduler containers use this same image and override the command with
# either the console script or the equivalent subcommand:
#   ["doghouse-worker"]
#   ["doghouse", "worker"]
CMD ["doghouse", "serve"]
