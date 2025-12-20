# Multi-stage Dockerfile for SvelteKit webapp
# Stage 1: Build the application using pnpm
FROM node:20-alpine AS builder

# Install pnpm globally
RUN corepack enable && corepack prepare pnpm@10.23.0 --activate

# Set working directory
WORKDIR /app

# Copy workspace configuration files
COPY pnpm-workspace.yaml ./
COPY package.json ./
COPY pnpm-lock.yaml* ./

# Copy backend directories needed for metadata generation
# The generate-apps-metadata.js script reads from backend/apps and backend/providers
COPY backend/apps ./backend/apps
COPY backend/providers ./backend/providers

# Copy frontend packages (needed for workspace dependencies)
COPY frontend/packages ./frontend/packages
COPY frontend/apps/web_app ./frontend/apps/web_app

# Install dependencies using pnpm
# This installs dependencies for the entire workspace
# The prepare script will run generate-apps-metadata.js which needs backend/apps
RUN pnpm install --frozen-lockfile

# Build the webapp
# The build command runs from the web_app directory
WORKDIR /app/frontend/apps/web_app

# Use the Docker-specific Svelte configuration for the build
# This swaps the Vercel adapter for the static adapter without changing the repo file
RUN cp svelte.config.docker.js svelte.config.js

# Build the webapp with the modified config
RUN pnpm build

# Stage 2: Serve the built application with a simple HTTP server
# Using serve package for lightweight static file serving
FROM node:20-alpine

# Install wget for health checks and serve for static file serving
RUN apk add --no-cache wget && \
    npm install -g serve@14.2.3

# Copy built files from builder stage
# SvelteKit with adapter-static outputs to 'build' directory
COPY --from=builder /app/frontend/apps/web_app/build /app/build

# Set working directory to the build directory
WORKDIR /app/build

# Expose port 5173 (Vite's default port, commonly used for frontend apps)
# Note: Port 3000 is used by Grafana
EXPOSE 5173

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:5173/ || exit 1

# Serve the static files
# -s: Single-page application mode (fallback to index.html for all routes)
# -l: Listen on all interfaces (0.0.0.0)
# -p: Port 5173 (Vite's default port)
CMD ["serve", "-s", ".", "-l", "5173"]

