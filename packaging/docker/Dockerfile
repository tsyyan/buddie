# The release image: the candidate's own wheel, nothing rebuilt (release.yml, stage `image`). MCP over stdio by
# default, for catalogs that run servers in containers (Docker MCP Catalog, the MCP Registry's OCI entry):
#   docker run -i --rm ghcr.io/tsyyan/buddie:VERSION
# Streamable HTTP for a remote server: add `serve --http -p 8000:8000` (docs/deploy.md). In a container buddie checks
# quotes, numbers and pr:/ci: anchors; it has no repository, session transcript or machine of the caller's.
FROM python:3.13-slim

ARG VERSION
LABEL org.opencontainers.image.title="buddie" \
      org.opencontainers.image.description="Checks AI agents' claims against primary evidence, without a model" \
      org.opencontainers.image.source="https://github.com/tsyyan/buddie" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      io.modelcontextprotocol.server.name="io.github.tsyyan/buddie"

# pdftotext reads PDF sources; nothing else is needed (buddie has no Python dependencies)
RUN apt-get update -q && apt-get install -y -q --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY dist/ /tmp/dist/
RUN test -n "$VERSION" && pip install --no-cache-dir --no-index "/tmp/dist/buddie-${VERSION}-py3-none-any.whl" \
    && rm -rf /tmp/dist && useradd --create-home --uid 10001 buddie && mkdir /data && chown buddie /data

USER buddie
ENV VERBATIM_STORE=/data/store BUDDIE_HTTP_HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1 BUDDIE_DEFAULT_REPOS=none
VOLUME /data
ENTRYPOINT ["buddie"]
CMD ["serve"]
