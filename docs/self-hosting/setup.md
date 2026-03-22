# OpenMates Self-Hosting Edition

This guide provides comprehensive instructions for setting up and running OpenMates on your own infrastructure.

> **Note:** The self-hosting edition currently only supports API-based AI models (requiring internet connection to external AI providers). Offline model support is planned for 2026.

## Prerequisites

Before starting, ensure your system has:

- Linux (Ubuntu/Debian recommended) or macOS
- At least 4GB RAM (8GB+ recommended)
- 20GB+ available disk space
- Internet connection for downloading dependencies

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/glowingkitty/OpenMates
cd OpenMates
```

### 2. Run the Setup Script

The setup script automatically installs dependencies and configures your environment:

```bash
chmod +x setup.sh
./setup.sh
```

**What the setup script does:**

- Checks for Docker, Docker Compose, and pnpm
- Installs missing dependencies (requires sudo)
- Creates your `.env` configuration file
- Generates necessary security secrets
- Sets up Docker network configuration

_Note: Designed for Debian-based systems. For other OS, install dependencies manually._

### 3. Configure API Keys

Edit the generated `.env` file to add your API keys:

```bash
nano .env
```

Add keys for services you want to use. See the [.env.example](../.env.example) file for the complete list of available API keys.

### 4. Start Backend Services

Start all backend services (API, database, etc.):

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml up -d
```

**For development with admin UIs** (includes Directus CMS and Grafana monitoring):

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

Admin interfaces will be available at:

- **Directus CMS**: http://localhost:8055
- **Grafana Monitoring**: http://localhost:3000

### 5. Verify Secret Import

Check that your API keys were imported successfully:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs vault-setup
```

If import was successful, replace actual keys in `.env` with `IMPORTED_TO_VAULT`:

```env
SECRET__MAILJET__API_KEY=IMPORTED_TO_VAULT
```

### 6. Start Frontend

You have two options for running the frontend:

#### Option A: Development Mode (Recommended for Testing)

For development/testing, run the frontend in dev mode with a custom API URL:

```bash
VITE_API_URL=http://YOUR_SERVER_IP:8000 pnpm --filter web_app dev --host 0.0.0.0 --port 5173
```

Replace `YOUR_SERVER_IP` with your actual server IP address (e.g., `192.168.1.100`).

_Note: First load may take up to a minute while Svelte builds files._

#### Option B: Production Build (Recommended for Deployment)

For production deployments, build the webapp with your API URL baked in:

```bash
# Build the webapp Docker image with your API URL
docker compose --env-file .env -f backend/core/docker-compose.yml build webapp \
  --build-arg VITE_API_URL=http://YOUR_SERVER_IP:8000

# Or build directly with pnpm (without Docker)
VITE_API_URL=http://YOUR_SERVER_IP:8000 pnpm --filter web_app build
```

**Important**: `VITE_API_URL` must be set at **build time** because Vite embeds environment variables into the JavaScript bundle during compilation.

To enable the webapp service, uncomment it in `backend/core/docker-compose.yml` and run:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml up -d webapp
```

### 7. Get Your Invite Code

Find the initial signup invite code:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs cms-setup
```

### 8. Access OpenMates

Open http://localhost:5173 in your browser and sign up using the invite code.

<!--
## Admin Account Setup

After setting up OpenMates, you'll want to create an admin account to manage server settings and community features.

### Creating an Admin Account

1. **Generate an admin token** (30-second expiration for security):
   ```bash
   docker exec -it openmates-api python /app/scripts/create_admin_token.py
   ```

   This will output:
   ```
   Admin token created successfully!
   Token: abc123xyz (expires in 30 seconds)

   To use this token:
   1. Log into OpenMates at http://localhost:5173
   2. Go to Settings
   3. Navigate to: settings/server/become-admin
   4. Enter the token within 30 seconds
   ```

2. **Use the token immediately**:
   - Log into OpenMates
   - Open Settings
   - Navigate directly to the become-admin page by visiting:
     `http://localhost:5173/settings/server/become-admin`
   - Enter the token within 30 seconds
   - You'll be granted admin privileges

3. **Access server settings**:
   - After becoming admin, you'll see "Server" in your Settings menu
   - Server settings include:
     - **Community Suggestions**: Manage demo chats shared by users
     - **Software Updates**: Update OpenMates to newer versions
     - **Admin Management**: Create additional admin tokens

### Admin Features

Once you have admin access, you can:

- **Manage community content**: Review and approve shared chats for demo use
- **Monitor system health**: Access detailed logs and metrics
- **Update software**: Install updates through the web interface
- **Manage users**: Create additional admin accounts when needed
-->

## Production Deployment

For production use, consider these additional steps:

### Reverse Proxy Setup (Caddy)

1. **Copy configuration template**:

   ```bash
   cp deployment/Caddyfile.example deployment/prod/Caddyfile.prod
   ```

2. **Configure domains and TLS**:

   ```caddyfile
   api.yourdomain.com {
       reverse_proxy api:8000
       header {
           Access-Control-Allow-Origin https://app.yourdomain.com
       }
   }

   app.yourdomain.com {
       reverse_proxy webapp:5173
       tls your-email@example.com
   }
   ```

3. **Use the configuration**:
   See [deployment/README.md](../architecture/servers.md) for detailed instructions.

### Security Considerations

- **Change default secrets**: Regenerate all secrets in production
- **Use HTTPS**: Configure proper TLS certificates
- **Network security**: Use Docker networks to isolate services
- **Regular updates**: Keep OpenMates and dependencies updated
- **Backup data**: Regular backups of database and user data
<!-- - **Admin token security**: Admin tokens expire after 30 seconds for security -->

### Environment Variables

Key production environment variables:

```env
# Domain configuration
FRONTEND_ORIGIN=https://app.yourdomain.com
API_DOMAIN=api.yourdomain.com

# Database (consider external database for production)
DB_HOST=your-production-db-host
DB_NAME=openmates_prod
DB_USER=openmates_user
DB_PASSWORD=secure-password

# Cache configuration
REDIS_URL=redis://your-redis-host:6379

# Email configuration (required for admin notifications)
SECRET__MAILJET__API_KEY=your_production_mailjet_key
SECRET__MAILJET__SECRET_KEY=your_production_mailjet_secret
```

### Frontend API URL Configuration

The frontend needs to know where to reach the backend API. For self-hosted deployments, you **must** set `VITE_API_URL` at build time:

| Variable       | Description                                         | Example                     |
| -------------- | --------------------------------------------------- | --------------------------- |
| `VITE_API_URL` | Full URL to your API server (for self-hosted)       | `http://192.168.1.100:8000` |
| `VITE_ENV`     | Optional: Set to `production` for cloud deployments | `production`                |

**Why build time?** Vite is a build-time bundler that replaces `import.meta.env.VITE_*` with actual values during compilation. Unlike server-side environment variables, these cannot be changed at runtime.

**Options for different setups:**

1. **Direct IP access**: `VITE_API_URL=http://192.168.1.100:8000`
2. **Hostname access**: `VITE_API_URL=http://myserver.local:8000`
3. **Reverse proxy with same origin**: `VITE_API_URL=` (empty, uses relative URLs - requires proxy config)
4. **Reverse proxy with different subdomain**: `VITE_API_URL=https://api.yourdomain.com`

## Management Commands

### Service Management

**View logs**:

```bash
# All services
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f

# Specific service
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api
```

**Restart services**:

```bash
# All services
docker compose --env-file .env -f backend/core/docker-compose.yml restart

# Specific service
docker compose --env-file .env -f backend/core/docker-compose.yml restart api
```

**Stop services**:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml down
```

### Development Workflow

**Restart backend for development** (excludes webapp for hot-reload):

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && \
docker volume rm openmates-cache-data && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api cms cms-database cms-setup task-worker task-scheduler app-ai app-web app-videos app-news app-maps app-ai-worker app-web-worker cache vault vault-setup prometheus cadvisor loki promtail && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d --scale webapp=0
```

**Start frontend development server**:

```bash
pnpm --filter web_app dev --host 0.0.0.0 --port 5173
```

## Troubleshooting

### Complete System Reset

If you encounter persistent issues:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && \
docker volume rm openmates-cache-data && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

This will:

- Stop all services
- Clear cached data
- Rebuild all containers
- Start with fresh state

### Common Issues

**Services won't start**:

- Check Docker is running: `docker info`
- Verify ports aren't in use: `lsof -i :8000` (API port)
- Check disk space: `df -h`

**Frontend won't load**:

- Ensure backend is running: `docker compose ps`
- Check API health: `curl http://localhost:8000/health`
- Verify pnpm dependencies: `pnpm install`

**Frontend shows "localhost:8000" connection errors when accessing from network**:

- The frontend API URL is baked in at build time
- Rebuild with your server's IP: `VITE_API_URL=http://YOUR_SERVER_IP:8000 pnpm --filter web_app build`
- Or for development: `VITE_API_URL=http://YOUR_SERVER_IP:8000 pnpm --filter web_app dev --host 0.0.0.0`
- Check browser console for the actual API URLs being requested
- Ensure CORS is configured on the backend to allow your frontend origin

<!--
**Admin token issues**:
- Tokens expire after 30 seconds - generate a new one
- Ensure you're logged in before using the token
- Check container is running: `docker ps | grep openmates-api`
-->

**Database connection errors**:

- Check database container: `docker compose logs cms-database`
- Verify network connectivity: `docker network ls`
- Reset database if needed: `docker volume rm openmates-cms-database-data`

## Getting Help

- **GitHub Issues**: Report bugs and feature requests
- **Documentation**: Check other files in `/docs` directory
- **Community**: Join our Discord for community support
- **Logs**: Always check service logs when troubleshooting

## License & Contributing

OpenMates is licensed under AGPL v3. Contributions welcome! See [contributing.md](../contributing/contributing.md) for guidelines.
