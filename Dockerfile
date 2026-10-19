# buddie as a remote MCP server (Streamable HTTP at /mcp). docs/deploy.md: settings, hosting, connecting clients.
FROM python:3.13-slim

# pdftotext reads PDF sources; nothing else is needed (buddie has no Python dependencies)
RUN apt-get update -q && apt-get install -y -q --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY buddie ./buddie
COPY verbatim ./verbatim
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 buddie && mkdir /data && chown buddie /data

USER buddie
ENV VERBATIM_STORE=/data/store BUDDIE_HTTP_HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"
CMD ["buddie", "serve", "--http"]
