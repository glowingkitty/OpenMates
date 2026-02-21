# Transition to Dokploy on Hetzner

This document outlines the migration from Vercel (frontend) + manual Docker Compose deployment (backend) to a self-hosted Dokploy setup on Hetzner VMs.

## Table of Contents

1. [Current vs Target Architecture](#current-vs-target-architecture)
2. [Why Dokploy](#why-dokploy)
3. [Infrastructure Setup](#infrastructure-setup)
4. [Migration Steps](#migration-steps)
5. [Deployment Workflow](#deployment-workflow)
6. [Cache Handling](#cache-handling)
7. [Rollback Procedures](#rollback-procedures)
8. [Cost Comparison](#cost-comparison)
9. [Checklist](#checklist)

---

## Current vs Target Architecture

### Current Setup

```
┌─────────────────────────────────────────────────────────────┐
│                     DEVELOPMENT                              │
│  ┌─────────────────┐      ┌─────────────────┐               │
│  │ Hetzner VM      │      │ Vercel Dev      │               │
│  │ Backend Dev     │      │ Frontend Dev    │               │
│  │ (SSH + manual   │      │ (auto-deploy)   │               │
│  │  docker compose)│      │                 │               │
│  └─────────────────┘      └─────────────────┘               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     PRODUCTION                               │
│  ┌─────────────────┐      ┌─────────────────┐               │
│  │ Hetzner VM      │      │ Vercel Prod     │               │
│  │ Backend Prod    │      │ Frontend Prod   │               │
│  │ (SSH + manual)  │      │ (auto-deploy)   │               │
│  └─────────────────┘      └─────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

**Pain Points:**

- Manual SSH + docker compose for backend deploys (~1-2 min downtime)
- Vercel free tier exceeded (Edge Requests: 1.6M/1M)
- US provider dependency (Vercel)
- Inconsistent deployment process between frontend/backend

### Target Setup

```
┌─────────────────────────────────────────────────────────────┐
│   Hetzner VM - Development (existing + optional Dokploy)    │
│                                                             │
│  For active coding:                                         │
│  • SSH in, edit code                                        │
│  • docker compose up (backend, localhost testing)           │
│  • pnpm dev (frontend on localhost:5173)                    │
│                                                             │
│  For staged deployments (optional):                         │
│  • Dokploy auto-deploys dev branch                          │
│  • dev.openmates.org → deployed dev frontend                │
│  • api-dev.openmates.org → deployed dev backend             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│           Hetzner VM - Frontend Production (Dokploy)        │
│                                                             │
│  Dokploy manages:                                           │
│  • openmates.org (static SvelteKit frontend)                │
│  • Auto-deploys main/prod branch                            │
│  • Zero-downtime rolling updates                            │
│  • SSL via Traefik + Let's Encrypt                          │
│                                                             │
│  Isolated from backend - no database access, no secrets     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│           Hetzner VM - Backend Production (Dokploy)         │
│                                                             │
│  Dokploy manages:                                           │
│  • api.openmates.org (API + all backend services)           │
│  • PostgreSQL, Dragonfly, Vault, Celery workers             │
│  • Auto-deploys main/prod branch                            │
│  • Zero-downtime rolling updates                            │
│  • SSL via Traefik + Let's Encrypt                          │
│                                                             │
│  Contains all sensitive data, isolated from public frontend │
└─────────────────────────────────────────────────────────────┘
```

**Security Benefits of Separation:**

- **Blast radius:** Frontend compromise doesn't expose backend/database
- **Network isolation:** Frontend VM has no access to internal backend services
- **Resource isolation:** Frontend traffic spikes don't affect backend performance
- **Different attack surfaces:** Static files vs API endpoints require different security postures

---

## Why Dokploy

### Dokploy Features

| Feature                    | Description                                                         |
| -------------------------- | ------------------------------------------------------------------- |
| **Zero-downtime deploys**  | Rolling updates - old containers serve traffic while new ones build |
| **Git-based deployment**   | Push to trigger automatic deployment                                |
| **Docker Compose support** | Native support for existing docker-compose.yml                      |
| **Automatic SSL**          | Traefik + Let's Encrypt, auto-renewal                               |
| **Web UI**                 | Dashboard for logs, monitoring, rollbacks                           |
| **Multi-server**           | Can manage multiple VMs from one Dokploy instance                   |
| **Open source**            | Self-hosted, no vendor lock-in                                      |
| **EU-based option**        | Run entirely on Hetzner (Germany)                                   |

### What Dokploy Replaces

| Before                     | After                     |
| -------------------------- | ------------------------- |
| Vercel (frontend hosting)  | Dokploy + Traefik         |
| Manual SSH deploys         | Git push → auto-deploy    |
| `docker compose down/up`   | Rolling container updates |
| Manual SSL cert management | Automatic Let's Encrypt   |

---

## Infrastructure Setup

### Recommended VM Specifications

| VM                | Purpose                               | Hetzner Model | Specs                              | Cost      |
| ----------------- | ------------------------------------- | ------------- | ---------------------------------- | --------- |
| **Dev**           | SSH coding + optional Dokploy staging | CX32          | 4 vCPU, 8GB RAM, 80GB SSD          | ~€9/mo    |
| **Frontend Prod** | Static SvelteKit frontend only        | CX22          | 2 vCPU, 4GB RAM, 40GB SSD          | ~€4.35/mo |
| **Backend Prod**  | API, databases, workers, monitoring   | CX32 or CX42  | 4-8 vCPU, 8-16GB RAM, 80-160GB SSD | ~€9-18/mo |

**Why separate frontend VM:**

- Static files require minimal resources (CX22 is plenty)
- No database credentials or secrets on frontend VM
- If frontend is DDoS'd or compromised, backend remains unaffected
- Can scale/restart independently

**Location:** Falkenstein (FSN) or Nuremberg (NBG) - same datacenter for all VMs for lowest latency between frontend→backend API calls.

**Total estimated cost:** ~€22-31/mo (vs Vercel Pro $20/mo + overages + current backend VM)

### Dokploy Installation

Install Dokploy on each production VM:

```bash
# On Frontend Prod VM
curl -sSL https://dokploy.com/install.sh | sh

# On Backend Prod VM
curl -sSL https://dokploy.com/install.sh | sh
```

This installs:

- Dokploy application
- Traefik (reverse proxy)
- Docker (if not present)

Access Dokploy UI at: `http://<VM_IP>:3000`

> **Tip:** Restrict port 3000 (Dokploy UI) to your IP only via firewall.

### Domain Configuration

Point DNS records to the **separate** VMs:

```
# Frontend VM
A    openmates.org         → <FRONTEND_VM_IP>
A    www.openmates.org     → <FRONTEND_VM_IP>

# Backend VM
A    api.openmates.org     → <BACKEND_VM_IP>

# Development (optional)
A    dev.openmates.org     → <DEV_VM_IP>
A    api-dev.openmates.org → <DEV_VM_IP>
```

Traefik on each VM will handle SSL certificates automatically for its domains.

---

## Migration Steps

### Phase 1: Prepare Production VMs

#### 1a. Frontend Production VM

1. **Provision Hetzner VM** (CX22 - lightweight for static files)
2. **Install Dokploy**
   ```bash
   curl -sSL https://dokploy.com/install.sh | sh
   ```
3. **Configure firewall**

   ```bash
   # Allow public web traffic
   ufw allow 22/tcp    # SSH
   ufw allow 80/tcp    # HTTP (for Let's Encrypt)
   ufw allow 443/tcp   # HTTPS

   # Restrict Dokploy UI to your IP only
   ufw allow from <YOUR_IP> to any port 3000

   ufw enable
   ```

4. **Access Dokploy UI** at `http://<FRONTEND_VM_IP>:3000` and create admin account

#### 1b. Backend Production VM

1. **Provision Hetzner VM** (CX32 or CX42 - needs more resources)
2. **Install Dokploy**
   ```bash
   curl -sSL https://dokploy.com/install.sh | sh
   ```
3. **Configure firewall**

   ```bash
   # Allow public web traffic (API endpoints)
   ufw allow 22/tcp    # SSH
   ufw allow 80/tcp    # HTTP (for Let's Encrypt)
   ufw allow 443/tcp   # HTTPS

   # Restrict Dokploy UI to your IP only
   ufw allow from <YOUR_IP> to any port 3000

   # Block all other incoming traffic (internal services not exposed)
   ufw enable
   ```

4. **Access Dokploy UI** at `http://<BACKEND_VM_IP>:3000` and create admin account

### Phase 2: Configure Frontend Deployment

1. **In Dokploy UI:**
   - Create new Application
   - Source: Git repository (GitHub/GitLab)
   - Branch: `main` or `prod`
   - Build method: Dockerfile
   - Dockerfile path: `frontend/apps/web_app/Dockerfile`

2. **Configure build context:**
   - Build context: `/` (project root, since Dockerfile needs backend/ for metadata)

3. **Configure domain:**
   - Domain: `openmates.org`
   - SSL: Enable (Let's Encrypt)

4. **Configure environment variables** (if any)

5. **Set up webhook:**
   - Copy webhook URL from Dokploy
   - Add to GitHub repository settings → Webhooks

### Phase 3: Configure Backend Deployment

**Option A: Docker Compose (Recommended)**

1. **In Dokploy UI:**
   - Create new "Compose" application
   - Upload or link `backend/core/docker-compose.yml`
   - Configure environment variables from `.env`

2. **Adjust docker-compose.yml for production:**
   - Remove development volume mounts (code mounts)
   - Ensure images are built, not mounted
   - Configure production environment variables

3. **Configure domains:**
   - `api.openmates.org` → backend service (port 8000)

**Option B: Individual Services**

Create separate Dokploy applications for each service if you need more granular control.

### Phase 4: DNS Cutover

1. **Test deployments** on temporary domains first
2. **Update DNS records:**
   - `openmates.org` → Frontend VM IP
   - `api.openmates.org` → Backend VM IP
3. **Verify SSL certificates** are issued on both VMs
4. **Monitor for errors** in Dokploy logs on both VMs
5. **Test frontend→backend communication** (API calls from frontend)

### Phase 5: Decommission Vercel

1. Verify production is stable on Dokploy
2. Remove Vercel deployment
3. Cancel Vercel subscription (if applicable)

---

## Deployment Workflow

### Before (Manual)

```bash
# SSH into production server
ssh prod-server

# Navigate to project
cd /path/to/OpenMates

# Pull latest changes
git pull origin main

# Stop everything (DOWNTIME STARTS)
docker compose down

# Delete cache volume
docker volume rm openmates-cache-data

# Rebuild all services
docker compose build api cms cms-database cms-setup task-worker \
  task-scheduler app-ai app-web app-videos app-news app-maps \
  app-ai-worker app-web-worker cache vault vault-setup \
  prometheus cadvisor loki promtail

# Start everything (DOWNTIME ENDS ~1-2 minutes later)
docker compose up -d
```

### After (Dokploy)

```bash
# Just push your changes
git push origin main

# Done! Dokploy handles:
# 1. Webhook received
# 2. Pull code
# 3. Build changed containers (old ones still running)
# 4. Health check new containers
# 5. Switch traffic (~0 downtime)
# 6. Run post-deploy hooks (cache flush)
# 7. Remove old containers
```

### Monitoring Deployments

- **Dokploy UI:** Real-time build logs, deployment history
- **Rollback:** One-click rollback to previous version
- **Alerts:** Configure notifications (Discord, Slack, email)

---

## Cache Handling

### Current Approach (Problematic)

```bash
docker volume rm openmates-cache-data
```

This is a "nuclear option" that:

- Causes downtime (containers must be stopped)
- Loses all cache data unnecessarily
- Takes time to recreate volume

### Recommended Approach

**Option 1: Post-deploy hook (simple)**

Configure in Dokploy:

```bash
docker exec cache redis-cli FLUSHALL
```

This clears all keys without removing the volume or stopping containers.

**Option 2: Versioned cache keys (best)**

Add deployment version to cache keys:

```python
# backend/core/api/app/utils/cache.py
import os

# Set by Dokploy or from git commit hash
DEPLOY_VERSION = os.environ.get('DEPLOY_VERSION', 'v1')

def make_cache_key(key: str) -> str:
    """Prefix all cache keys with deployment version."""
    return f"{DEPLOY_VERSION}:{key}"
```

In Dokploy, set `DEPLOY_VERSION` to:

- Git commit short hash: `${GIT_COMMIT_SHA:0:7}`
- Or auto-incrementing deployment ID

Benefits:

- No cache flush needed
- Old keys expire naturally via TTL
- Zero downtime, zero data loss

**Option 3: Selective invalidation**

Only flush specific key patterns:

```bash
# Flush only user-related cache, keep app config
docker exec cache redis-cli --scan --pattern "user:*" | xargs -r docker exec -i cache redis-cli DEL
```

### When to Actually Delete the Volume

Only delete `openmates-cache-data` if:

- Dragonfly/Redis version upgrade with incompatible data format
- Corrupted cache data causing errors
- Major schema changes in cached data structures

For these cases, add a pre-deploy hook in Dokploy:

```bash
docker volume rm openmates-cache-data || true
```

---

## Rollback Procedures

### Dokploy Rollback

1. **Open Dokploy UI** (on the relevant VM - frontend or backend)
2. **Navigate to application**
3. **Click "Deployments" tab**
4. **Select previous working deployment**
5. **Click "Redeploy"**

Traffic switches back to the previous version in seconds.

### Manual Rollback (Emergency)

If Dokploy is inaccessible:

```bash
# SSH into the relevant production VM
ssh frontend-prod   # or backend-prod

# List recent images
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}" | head -20

# Manually run previous image
docker run -d --name webapp-rollback <previous-image-tag>

# Update Traefik to point to rollback container
# (Or use docker compose with pinned image tags)
```

### Database Rollback (Backend VM only)

Database volumes persist across deployments. For database rollbacks:

1. Restore from backup (configure automated backups separately)
2. Or use Directus snapshot restore

### Independent Rollbacks

Since frontend and backend are on separate VMs:

- **Frontend issue:** Rollback frontend only, backend unaffected
- **Backend issue:** Rollback backend only, frontend continues serving (may show errors for API calls)
- **Both:** Rollback both independently

This isolation means you can quickly identify which component caused an issue.

---

## Cost Comparison

### Current Setup

| Service                  | Cost                              |
| ------------------------ | --------------------------------- |
| Vercel Free (exceeded)   | $0 + forced upgrade or throttling |
| Vercel Pro (if upgraded) | $20/mo + overage fees             |
| Hetzner Backend Dev VM   | ~€9-18/mo                         |
| Hetzner Backend Prod VM  | ~€9-18/mo                         |
| **Total**                | **~€38-56/mo** (with Vercel Pro)  |

### Dokploy Setup

| Service                             | Cost                     |
| ----------------------------------- | ------------------------ |
| Hetzner Dev VM (CX32)               | ~€9/mo                   |
| Hetzner Frontend Prod VM (CX22)     | ~€4.35/mo                |
| Hetzner Backend Prod VM (CX32/CX42) | ~€9-18/mo                |
| Dokploy                             | Free (self-hosted)       |
| SSL (Let's Encrypt)                 | Free                     |
| **Total**                           | **~€22-31/mo (~$24-34)** |

### Savings

- **Monthly:** ~€16-25 saved (vs Vercel Pro setup)
- **Annual:** ~€192-300 saved
- **No overage fees:** Unlimited requests on your own infrastructure
- **No US provider dependency:** 100% EU-hosted (Hetzner Germany)
- **Better security:** Frontend/backend isolation

---

## Checklist

### Pre-Migration

**Frontend Production VM:**

- [ ] Provision Hetzner VM (CX22, Falkenstein/Nuremberg)
- [ ] Install Dokploy
- [ ] Configure firewall (22, 80, 443 open; 3000 restricted to your IP)
- [ ] Create Dokploy admin account
- [ ] Test Dokploy UI access

**Backend Production VM:**

- [ ] Provision Hetzner VM (CX32/CX42, same datacenter as frontend)
- [ ] Install Dokploy
- [ ] Configure firewall (22, 80, 443 open; 3000 restricted to your IP)
- [ ] Create Dokploy admin account
- [ ] Test Dokploy UI access

### Frontend Migration (on Frontend VM)

- [ ] Create frontend application in Dokploy
- [ ] Configure Git repository connection
- [ ] Set Dockerfile path: `frontend/apps/web_app/Dockerfile`
- [ ] Set build context to project root (needs backend/ for metadata generation)
- [ ] Configure domain: `openmates.org`
- [ ] Enable SSL
- [ ] Set up GitHub webhook
- [ ] Test deployment on temporary domain
- [ ] Verify build completes successfully
- [ ] Test all frontend routes
- [ ] Verify API calls to backend work (CORS configured correctly)

### Backend Migration (on Backend VM)

- [ ] Create Docker Compose application in Dokploy
- [ ] Upload/configure docker-compose.yml (production version without dev mounts)
- [ ] Configure all environment variables from `.env`
- [ ] Configure domain: `api.openmates.org`
- [ ] Enable SSL
- [ ] Set up GitHub webhook
- [ ] Configure post-deploy hook: `docker exec cache redis-cli FLUSHALL`
- [ ] Test deployment
- [ ] Verify all services healthy (API, workers, databases)
- [ ] Test API endpoints
- [ ] Verify CORS allows requests from `openmates.org`

### DNS Cutover

- [ ] Update DNS: `openmates.org` → Frontend VM IP
- [ ] Update DNS: `api.openmates.org` → Backend VM IP
- [ ] Wait for DNS propagation (~15 min to 24 hours)
- [ ] Verify SSL certificates issued on both VMs
- [ ] Test production domains
- [ ] Test frontend→backend API communication
- [ ] Monitor error logs on both VMs

### Post-Migration

- [ ] Verify zero-downtime deploys working on both VMs
- [ ] Test rollback procedure on both VMs
- [ ] Configure monitoring alerts in both Dokploy instances
- [ ] Document any environment-specific configurations
- [ ] Remove Vercel deployment
- [ ] Cancel Vercel subscription (if applicable)
- [ ] Update CI/CD documentation
- [ ] Inform team of new deployment workflow
- [ ] Set up regular backups for backend VM (database, vault)

---

## Security Considerations

### Network Isolation

With separate VMs, the frontend has **no direct access** to backend internal services:

```
┌──────────────────┐     HTTPS only      ┌──────────────────┐
│   Frontend VM    │ ─────────────────── │   Backend VM     │
│                  │   api.openmates.org │                  │
│  • Static files  │                     │  • API (exposed) │
│  • No secrets    │     ┌───────────────┤  • PostgreSQL    │
│  • No DB access  │     │ NOT EXPOSED   │  • Dragonfly     │
│                  │     │               │  • Vault         │
└──────────────────┘     │               │  • Celery        │
                         │               │  • Grafana       │
                         └───────────────┴──────────────────┘
```

### What Each VM Has Access To

| Resource             | Frontend VM | Backend VM   |
| -------------------- | ----------- | ------------ |
| Database credentials | ❌          | ✅           |
| Vault secrets        | ❌          | ✅           |
| API keys             | ❌          | ✅           |
| User data            | ❌          | ✅           |
| Internal services    | ❌          | ✅           |
| Public internet      | ✅          | ✅ (limited) |

### Firewall Rules

**Frontend VM (minimal attack surface):**

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                          # SSH
ufw allow 80/tcp                          # HTTP (Let's Encrypt)
ufw allow 443/tcp                         # HTTPS
ufw allow from <YOUR_IP> to any port 3000 # Dokploy UI (restricted)
```

**Backend VM (more restrictive):**

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                          # SSH
ufw allow 80/tcp                          # HTTP (Let's Encrypt)
ufw allow 443/tcp                         # HTTPS (API only)
ufw allow from <YOUR_IP> to any port 3000 # Dokploy UI (restricted)
# Internal ports (5432, 6379, 8200, etc.) NOT exposed
```

### If Frontend is Compromised

With this architecture:

- Attacker gains access to static HTML/JS/CSS only
- No database credentials to steal
- No internal services to pivot to
- Backend remains secure
- User data remains protected

### Secrets Management

- **Frontend:** No `.env` secrets needed (API URL is public anyway)
- **Backend:** All secrets in Dokploy environment variables or Vault
- **Never commit secrets** to git repository

---

## Troubleshooting

### Build Fails

1. Check build logs in Dokploy UI
2. Verify Dockerfile path is correct
3. Ensure build context includes all required files
4. Check for missing environment variables

### SSL Certificate Not Issued

1. Verify DNS points to correct IP
2. Check Traefik logs: `docker logs traefik`
3. Ensure ports 80 and 443 are open
4. Wait for DNS propagation if recently changed

### Container Health Check Fails

1. Check container logs in Dokploy
2. Verify health check endpoint responds
3. Check internal networking between containers
4. Verify environment variables are set correctly

### Cache Issues After Deploy

1. Verify post-deploy hook ran: check Dokploy logs
2. Manually flush if needed: `docker exec cache redis-cli FLUSHALL`
3. Check Dragonfly logs: `docker logs cache`

---

## References

- [Dokploy Documentation](https://docs.dokploy.com/)
- [Dokploy GitHub](https://github.com/dokploy/dokploy)
- [Hetzner Cloud](https://www.hetzner.com/cloud)
- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Let's Encrypt](https://letsencrypt.org/)
