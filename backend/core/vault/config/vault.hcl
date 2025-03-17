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

# Enable UI
ui = true

# Disable memory lock (safe in container)
disable_mlock = true

# Explicitly set log level to debug for troubleshooting
log_level = "debug"
