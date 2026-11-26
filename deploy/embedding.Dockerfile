FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12-slim-bookworm AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /opt/valueflow
COPY pyproject.toml uv.lock README.md ./
COPY src/data ./src/data
RUN uv sync --locked --extra embed --no-dev

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models \
    PYTHONPATH=/opt/valueflow/src/data PATH=/opt/valueflow/.venv/bin:$PATH
WORKDIR /opt/valueflow
RUN groupadd --gid 10001 valueflow && useradd --uid 10001 --gid valueflow --no-create-home valueflow \
    && mkdir /models && chown 10001:10001 /models
COPY --from=dependencies /opt/valueflow/.venv ./.venv
COPY src/data ./src/data
USER 10001:10001
CMD ["python", "-m", "agetech_data.rag.serve", "--host", "0.0.0.0"]
