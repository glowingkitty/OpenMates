# Minimal Vault configuration

# Simple listener config - absolute minimum
listener "tcp" {
  address = "0.0.0.0:8200"
  tls_disable = true
}

# File storage with minimal config
storage "file" {
  path = "/vault/file"
}

# Explicitly set API address to avoid warning
api_addr = "http://0.0.0.0:8200"

# Disable UI — the web UI is not used and exposes an unnecessary attack surface.
# All Vault operations are performed via the API (by services and vault-setup).
ui = false

# Disable memory lock (safe in container)
disable_mlock = true

# Log level — use "info" in production (debug can expose sensitive request data in logs)
log_level = "info"
