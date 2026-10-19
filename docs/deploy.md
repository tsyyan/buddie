# Deploying buddie as a remote MCP server

ChatGPT, claude.ai and the Claude API's MCP connector cannot start a process on your machine: they reach MCP servers
over HTTPS. `buddie serve --http` is that server. It speaks Streamable HTTP (MCP 2025-06-18) at `/mcp`, needs only
the Python standard library, and keeps no sessions, so it scales by running more copies.

Claude Code, Claude Desktop and Codex do not need it: they run buddie locally over stdio, with more checks available
(see [What the remote server checks](#what-the-remote-server-checks)).

## Run it

```bash
pip install git+https://github.com/tsyyan/buddie
buddie serve --http                 # http://127.0.0.1:8000/mcp
```

With Docker:

```bash
docker build -t buddie .
docker run -p 8000:8000 -v buddie-data:/data buddie
curl http://127.0.0.1:8000/healthz
```

The image listens on `0.0.0.0:$PORT` (default 8000), runs as a non-root user and keeps snapshots in the `/data`
volume. CI builds it and checks `initialize`, `tools/list` and the address guard on every change.

## Settings

| Variable | Default | What |
|---|---|---|
| `PORT` | `8000` | port to listen on (most hosts set it) |
| `BUDDIE_HTTP_HOST` | `127.0.0.1` (`0.0.0.0` in the image) | address to listen on |
| `BUDDIE_HTTP_TOKEN` | unset | when set, every request needs `Authorization: Bearer <token>` |
| `BUDDIE_HTTP_ORIGINS` | unset | comma list of browser origins allowed; a request with any other `Origin` header gets 403 |
| `BUDDIE_HTTP_MAX_BYTES` | `1048576` | largest request body |
| `BUDDIE_HTTP_WORKERS` | `8` | tool calls at once; more get 503 with `Retry-After` |
| `VERBATIM_STORE` | `./.verbatim` (`/data/store` in the image) | snapshot store |
| `BUDDIE_GITHUB_TOKEN` | unset | token for `pr:`/`ci:` anchors; without it GitHub allows 60 requests an hour per IP |

## Hosting

Any host that runs a container and terminates TLS will do: Fly.io, Render, Railway, Google Cloud Run, or a VPS with
a reverse proxy such as Caddy. What matters:

- **HTTPS.** ChatGPT and claude.ai only connect to `https://` URLs. The server itself speaks plain HTTP behind the
  host's TLS.
- **A persistent volume at `/data`**, so snapshots survive restarts. It still works without one; it just fetches
  pages again.
- **A request timeout of at least 120 s** at the proxy. `verify_report` fetches every cited page that is not in the
  store yet.
- **Rate limits at the proxy** if the URL is public. Every call can make the server fetch up to 20 pages.

### Render (free plan)

[`render.yaml`](../render.yaml) is a Render Blueprint for this image on the free plan: Frankfurt, health check
`/healthz`, a redeploy on every commit to `main`. In the Render dashboard choose New → Blueprint, connect the
GitHub repository, and apply. The endpoint is then `https://<service>.onrender.com/mcp`.

What the free plan means for buddie:

- **Sleep.** After 15 minutes without requests the service sleeps, and the next request wakes it in about a
  minute. A client can time out on that first call. An external monitor that requests `/healthz` every 10 minutes
  keeps it awake; one service awake all month fits in the 750 free hours.
- **No disk.** Snapshots are kept in `/tmp/store` until the next restart. They are fetched again when needed.
- **No rate limiting in front.** Calls at once are capped by `BUDDIE_HTTP_WORKERS` (4 here); bandwidth over the
  free allowance suspends the service for the rest of the month.
- Render describes the free plan as not meant for production and may restart the service at any time.

A GitHub token for `pr:`/`ci:` anchors can be added later under the service's Environment as `BUDDIE_GITHUB_TOKEN`.
Give it no access beyond public data, since every caller's lookups use it.

A minimal Caddy front for a VPS:

```
buddie.example.org {
    reverse_proxy 127.0.0.1:8000
}
```

## Connect a client

The endpoint is `https://<your-host>/mcp`.

| Client | Where | Auth |
|---|---|---|
| ChatGPT | Settings → Apps & Connectors → Advanced → developer mode, then create a connector with the URL | no auth (ChatGPT offers OAuth or none) |
| claude.ai, Claude Desktop custom connector | Settings → Connectors → Add custom connector | no auth (OAuth or none) |
| Claude API, MCP connector | `mcp_servers: [{"type": "url", "url": ".../mcp", "name": "buddie", "authorization_token": "..."}]` | bearer token works |
| Codex, other MCP clients | a streamable HTTP server entry with the URL | bearer token works |

These menus move between releases. If a name differs, look for "connectors" or "MCP" in the client's settings.

ChatGPT and claude.ai cannot send a fixed bearer token today, so a server for them runs without
`BUDDIE_HTTP_TOKEN`. The URL is then open to anyone who knows it. Use rate limits, or keep a second copy with a token
for API clients. OAuth is not implemented yet.

## What the remote server checks

Anyone who can reach the URL can call the tools, so the remote server does less than the local one:

| | stdio (Claude Code, Desktop, Codex) | remote |
|---|---|---|
| quotes against page snapshots | yes | yes |
| numbers with a link | yes | yes |
| `pr:`, `ci:` on GitHub | yes | yes, public repos (or what `BUDDIE_GITHUB_TOKEN` can see) |
| `path#sha256`, `path@commit`, `fact=` | yes, against local checkouts | UNCHECKABLE: the server has no checkout of yours |
| `run:` against the session transcript | Claude Code only | UNCHECKABLE |
| `summary` tool, hook gate | Claude Code only | no |

The remote tools refuse every argument that names a file or directory on the server (`path`, `repos`, `store`,
`transcript`) and the `access` cascade. Pages are fetched only over http(s), on ports 80 and 443, from public
addresses. Every redirect hop is checked too, and the socket connects to the address that was checked, so a name
that resolves to `127.0.0.1`, `10.x`, `169.254.169.254` or similar is refused. That protects the cloud metadata
endpoint and anything else on the host's network.

## Privacy

The server sees the report text it is asked to check. It does not log that text: the access log has the method,
path and status only. The snapshots it keeps are of the public pages the reports cite, shared by all callers and
addressed by SHA-256. `BUDDIE_GITHUB_TOKEN` is used for every caller's `pr:`/`ci:` lookups, so give it no access
beyond public data. The local plugin's own data flows are described in [PRIVACY.md](../PRIVACY.md).
