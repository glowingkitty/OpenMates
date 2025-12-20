# Docker Setup for Webapp

This directory contains the Docker configuration for building and serving the SvelteKit webapp as a static site.

## Overview

The Docker setup uses a **multi-stage build** approach:

1. **Build Stage**: Uses Node.js with pnpm to build the SvelteKit application
2. **Serve Stage**: Uses `serve` (lightweight Node.js static file server) to serve the built files

The webapp container is designed to be reverse-proxied by **Caddy**, which handles TLS, compression, and security headers.

## Files

- `Dockerfile`: Multi-stage build configuration

## Building the Image

From the project root:

```bash
docker build -f frontend/apps/web_app/Dockerfile -t openmates-webapp .
```

Or using docker-compose:

```bash
cd backend/core
docker-compose build webapp
```

## Running the Container

The webapp service is configured in `backend/core/docker-compose.yml`. To run it:

```bash
cd backend/core
docker-compose up webapp
```

The webapp will be available on port 5173 inside the container (Vite's default port). **Caddy should reverse proxy to this container** (see Caddyfile configuration below).

## Caddy Configuration

Add the following to your Caddyfile to reverse proxy to the webapp container:

```caddy
# Replace <FRONTEND_DOMAIN> with your actual frontend domain
# e.g., app.yourdomain.com or yourdomain.com
<FRONTEND_DOMAIN> {
	log {
		output file /var/log/caddy/<FRONTEND_DOMAIN>.log {
			roll_size 100mb
			roll_keep 10
			roll_keep_for 720h
		}
		format json
		level INFO
	}

	encode gzip zstd

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "strict-origin-when-cross-origin"
		Permissions-Policy "geolocation=(), microphone=(), camera=(), interest-cohort=()"
		-Server
	}

	# For Docker Compose: use service name 'webapp:5173'
	# For standalone: use 'localhost:5173' or actual IP:port
	# Note: Port 5173 is Vite's default port (commonly used for frontend apps)
	# Port 3000 is used by Grafana
	reverse_proxy webapp:5173 {
		header_up Host {http.request.host}
		header_up X-Real-IP {http.request.remote}
	}
}
```

See `deployment/Caddyfile.example` for a complete example.

## Important Notes

### Adapter Configuration

**Production Build**: The Dockerfile automatically handles the adapter configuration. It uses a dedicated `svelte.config.docker.js` file (which uses `@sveltejs/adapter-static`) and copies it to `svelte.config.js` during the build process. This ensures the app is built as a static site suitable for containerized deployment.

**Vercel Deployments**: Your original `svelte.config.js` remains untouched in the repository (configured for `@sveltejs/adapter-vercel`), so regular Vercel deployments will continue to work without any changes.

### Build Output

- The build outputs to `frontend/apps/web_app/build/`
- The `serve` package serves files from `/app/build/` in the container
- The `serve` package handles SPA routing by falling back to `index.html` for all routes (via `-s` flag)

### Performance

- Caddy handles compression (gzip/zstd) and caching headers
- The `serve` package is lightweight and efficient for static file serving
- Static assets are served directly, with HTML files having no-cache headers

### Health Check

The container includes a health check that verifies the server is responding on port 5173.

## Development vs Production

For **development** with hot-reloading, you should run the SvelteKit dev server directly:

```bash
cd frontend/apps/web_app
pnpm dev
```

For **production**, use the Docker container which serves the pre-built static files. Caddy handles TLS, compression, and security headers.

