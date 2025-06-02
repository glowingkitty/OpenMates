# Use an official Node.js runtime as a parent image
FROM node:20-alpine AS base

# Install pnpm
RUN npm install -g pnpm

WORKDIR /app

# Copy pnpm workspace configuration files from the project root
COPY pnpm-workspace.yaml ./
COPY package.json ./

# Copy the entire frontend directory to make all workspace packages available
COPY frontend ./frontend

WORKDIR /app/frontend/apps/web_app

# Install all dependencies. PNPM will handle the workspace.
RUN pnpm install

# Use pnpm to run the dev script
CMD ["pnpm", "run", "dev", "--host"]
