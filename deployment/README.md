# Deployment Configuration

This directory contains deployment configuration files for OpenMates, including Caddy reverse proxy configurations.

## Caddy Configuration

### Template-Based Configuration Pattern

We follow a best practice pattern for managing Caddy configurations in an open-source repository:

- **Template/Reference Config**: `Caddyfile.example` is committed to the repository
  - Documents the expected public endpoints (e.g., `/api` → FastAPI, `/` → frontend)
  - Provides a reference for routing, security headers, and CORS configuration
  - Uses placeholder values that must be replaced with environment-specific values

- **Environment-Specific Overrides**: The following files are gitignored:
  - `Caddyfile.local` - Local development configuration
  - `Caddyfile.prod` - Production configuration
  - `Caddyfile.override` - Any additional overrides
  - `*/Caddyfile` - Any Caddyfile in subdirectories (e.g., `dev_server/Caddyfile`, `prod_server/Caddyfile`)

### Why This Pattern?

**Why commit the template:**

- New contributors can run the stack quickly (reverse proxy, TLS in dev, routing)
- Documents expected public endpoints and routing structure
- Avoids everyone reinventing proxy config slightly differently
- Serves as living documentation of the architecture

**Why not commit "the real one":**

- Production Caddyfiles often include environment-specific domains
- May contain internal network names and upstream addresses
- Could accidentally include secrets (basicauth hashes, internal paths, etc.)
- People might copy/paste it and assume it's safe

### Setup Instructions

#### For Local Development

1. **Copy the template:**

   ```bash
   cp deployment/Caddyfile.example deployment/dev_server/Caddyfile.local
   ```

2. **Edit the configuration:**
   - Replace `<API_DOMAIN>` with your development API domain (e.g., `api.yourdomain.com` or `api.dev.yourdomain.com`)
   - Replace `<FRONTEND_ORIGIN>` with your frontend origin (e.g., `https://yourdomain.com` or `https://app.yourdomain.com`)
   - Replace `<API_UPSTREAM>` with your API upstream address:
     - For Docker Compose: use service name like `api:8000`
     - For standalone Caddy: use `localhost:8000` or actual IP:port
   - Replace `<YOUR_EMAIL@example.com>` with your email for Let's Encrypt notifications

3. **Use the configuration:**
   - Point Caddy to your `Caddyfile.local` file
   - Or symlink it: `ln -s deployment/dev_server/Caddyfile.local /etc/caddy/Caddyfile`

#### For Production

1. **Copy the template:**

   ```bash
   cp deployment/Caddyfile.example deployment/prod_server/Caddyfile.prod
   ```

2. **Edit the configuration:**
   - Replace all placeholder values with production values
   - Update domains, origins, and upstream addresses
   - Ensure email is set for Let's Encrypt

3. **Deploy:**
   - Production config is typically managed via deployment tools (Terraform, Ansible, etc.)
   - Or manually copy to your production server

### Docker Compose Integration

If you're using Docker Compose, the Caddyfile can reference service names directly:

```caddy
reverse_proxy api:8000 {
    header_up Host {http.request.host}
}
```

This works because Docker Compose creates a network where services can reach each other by name.

### Additional Services

The template includes comments for adding additional services (Penpot, Etherpad, Jupyter, n8n, etc.). Uncomment and configure as needed for your environment.

### Security Notes

- Never commit environment-specific Caddyfiles that contain:
  - Real domain names (unless they're public)
  - Internal network addresses
  - Authentication credentials or hashes
  - Internal file paths
- Always review changes to `Caddyfile.example` before committing
- Use environment variables or secrets management for sensitive values when possible

### File Structure

```text
deployment/
├── README.md                    # This file
├── Caddyfile.example           # Template (committed)
├── dev_server/
│   ├── Caddyfile               # Dev config (gitignored)
│   └── Caddyfile.local         # Alternative dev config (gitignored)
└── prod_server/
    ├── Caddyfile               # Prod config (gitignored)
    └── Caddyfile.prod          # Alternative prod config (gitignored)
```

## Other Deployment Files

This directory may also contain:

- Terraform configurations for infrastructure as code
- Deployment scripts
- Environment-specific configuration files

All environment-specific files should follow the same pattern: commit templates/examples, gitignore actual configurations.
