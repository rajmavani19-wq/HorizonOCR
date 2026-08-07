# HorizonOCR Production Deployment

HorizonOCR is a private document-processing application. Deploy the Flask service and frontend together behind HTTPS on one origin whenever possible. This keeps authenticated cookies same-site and avoids exposing a public cross-origin API surface.

## Required environment

Set these values in your platform secret manager; do not commit a real `.env` file.

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_ENV=production` | Yes | Enables secure session-cookie behavior and requires a configured secret. |
| `SECRET_KEY` | Yes | Long, random secret used to sign sessions. Rotate through the platform secret manager. |
| `DATA_DIR` | Yes | Persistent, writable location for `horizonocr.db`. Mount this path to durable storage. |
| `TRUSTED_PROXY_HOPS` | Usually | Set to `1` behind one managed reverse proxy so HTTPS-aware security behavior is correct. |
| `ALLOWED_ORIGINS` | Split deployment only | Comma-separated HTTPS frontend origins. Leave empty for a same-origin deployment. |
| `MAX_UPLOAD_BYTES` | Optional | Upload cap; default is 50 MiB. |
| `MAX_DOCUMENT_PAGES` | Optional | PDF page cap; default is 25. |

Use `.env.example` as a non-secret reference only.

## Container deployment

Build and run the included production container with a durable volume mounted at `/var/lib/horizonocr`:

```bash
docker build -t horizonocr:prod .
docker run --rm -p 8080:8080 \
  -e APP_ENV=production \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  -e DATA_DIR=/var/lib/horizonocr \
  -e TRUSTED_PROXY_HOPS=1 \
  -v horizonocr-data:/var/lib/horizonocr \
  horizonocr:prod
```

Terminate TLS at a managed load balancer or reverse proxy and expose only HTTPS publicly. Keep the application container private behind that proxy where your platform supports it.

## Operational requirements

- Use persistent block storage for `DATA_DIR`; SQLite is not appropriate for ephemeral filesystems or horizontally replicated application instances.
- Run one application writer per SQLite database file. For multi-instance or high-throughput operation, migrate the persistence layer to a managed relational database before scaling replicas.
- Put an edge rate limiter and request-size limit in front of the service. The application includes process-local request limits as a second layer, not a distributed abuse-control system.
- Monitor `GET /api/health` from the platform health checker.
- Back up the SQLite database using a storage-aware, consistent backup process. Test restore procedures before launch.
- Rotate `SECRET_KEY` with a planned session invalidation window.
- Do not expose `database` files, model caches, logs, temporary folders, source code, or environment files through the web server.

## Deployment modes

### Recommended: same-origin private service

Serve `index.html`, static assets, and `/api/*` from this Flask/Gunicorn container behind one HTTPS hostname. Leave `window.API_BASE` empty.

### Split frontend and API

Use only when necessary. Configure the frontend with the exact HTTPS API origin and set `ALLOWED_ORIGINS` to the exact HTTPS frontend origin(s). Browsers require credentialed CORS for session cookies; wildcard origins are intentionally not supported.

Deploy the application as a single Web Service on Render (or Docker container) using render.yaml for same-origin authentication and data persistence.

## Pre-launch checklist

- [ ] `APP_ENV=production` and a managed `SECRET_KEY` are configured.
- [ ] The service has a persistent `DATA_DIR` volume and a tested database-backup plan.
- [ ] HTTPS, proxy trust, and health checks are configured.
- [ ] The desired same-origin or explicitly allowlisted split-origin topology is configured.
- [ ] The deployment host enforces network, request-size, and distributed rate-limit policies.
- [ ] A private test account has completed registration, login, upload, history, logout, and authorization-isolation checks.
