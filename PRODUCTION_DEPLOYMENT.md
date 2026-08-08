# HorizonOCR Production Deployment Guide

HorizonOCR is a private document-processing application. Deploy the Flask service and frontend together behind HTTPS on one origin whenever possible. This keeps authenticated cookies same-site and avoids exposing a public cross-origin API surface.

---

## 🔑 Required Environment Variables

Set these values in your platform secret manager; do not commit a real `.env` file.

| Variable | Required | Default / Purpose |
| --- | --- | --- |
| `APP_ENV` | Yes | Set to `production` for secure cookie behavior. |
| `SECRET_KEY` | Yes | Long, random secret used to sign user sessions. |
| `DATA_DIR` | Yes | Persistent, writable directory path for `horizonocr.db`. |
| `TRUSTED_PROXY_HOPS` | Yes | Set to `1` behind a reverse proxy (Render / Nginx / Cloudflare). |
| `ALLOWED_ORIGINS` | No | Comma-separated HTTPS origins (only for split frontend/API deployment). |
| `GITHUB_CLIENT_ID` | Optional | GitHub OAuth Client ID for GitHub Sign In. |
| `GITHUB_CLIENT_SECRET` | Optional | GitHub OAuth Client Secret for GitHub Sign In. |
| `MAX_UPLOAD_BYTES` | No | File upload limit in bytes (default: 50 MiB). |
| `MAX_DOCUMENT_PAGES` | No | PDF page extraction cap (default: 500 pages). |

---

## ☁️ Deployment Platforms

### Option 1: Render.com (Recommended Web Service)

HorizonOCR includes a ready-to-use [`render.yaml`](file:///f:/Antigravity%20Files/HorizonOCR/render.yaml) blueprint:

1. Connect your repository to Render.com.
2. Select **Web Service** and choose Python 3 runtime or Docker.
3. Configure environment variables (`APP_ENV=production`, `SECRET_KEY`, `DATA_DIR=/opt/render/data`, `TRUSTED_PROXY_HOPS=1`).
4. Attach a 1 GB+ Persistent Disk at `/opt/render/data` to preserve SQLite user data across restarts.

---

### Option 2: Google Cloud Platform (GCP Free Tier)

Deploy on GCP Compute Engine `e2-micro` (Always Free eligible in `us-central1` / `us-east1` / `us-west1`):

```bash
# SSH into your GCP VM instance
sudo apt update && sudo apt install -y docker.io git
sudo systemctl enable --now docker

# Clone repository and build Docker container
git clone https://github.com/YOUR_USERNAME/HorizonOCR.git
cd HorizonOCR
sudo docker build -t horizonocr:latest .

# Run container on Port 80
sudo docker run -d \
  --name horizonocr \
  --restart always \
  -p 80:8080 \
  -e APP_ENV=production \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  -e DATA_DIR=/var/lib/horizonocr \
  -e TRUSTED_PROXY_HOPS=1 \
  -v horizonocr-data:/var/lib/horizonocr \
  horizonocr:latest
```

---

### Option 3: Oracle Cloud Infrastructure (OCI Always Free)

Deploy on Oracle Cloud Ampere ARM or AMD Free VM instance:

```bash
# System setup & Docker installation
sudo apt update && sudo apt install -y docker.io git
sudo systemctl enable --now docker

# Run Docker container
docker build -t horizonocr .
docker run -d --name horizonocr --restart always -p 80:8080 \
  -e APP_ENV=production -e SECRET_KEY="$(openssl rand -hex 32)" \
  -e DATA_DIR=/var/lib/horizonocr -e TRUSTED_PROXY_HOPS=1 \
  -v horizonocr-data:/var/lib/horizonocr horizonocr
```

Open Port 80 in Oracle Security List and Ubuntu firewall (`iptables`).

---

## 🐳 Docker Deployment

Build and run the included production container locally or on any cloud server:

```bash
docker build -t horizonocr:prod .
docker run -d -p 8080:8080 \
  -e APP_ENV=production \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  -e DATA_DIR=/var/lib/horizonocr \
  -e TRUSTED_PROXY_HOPS=1 \
  -v horizonocr-data:/var/lib/horizonocr \
  horizonocr:prod
```

---

## 📋 Pre-Launch Checklist

- [ ] `APP_ENV=production` and a secure `SECRET_KEY` are configured.
- [ ] Durable volume storage is configured for `DATA_DIR`.
- [ ] Health check endpoint (`GET /api/health`) responds with `200 OK`.
- [ ] User registration, login, document upload, and history retrieval tested successfully.
