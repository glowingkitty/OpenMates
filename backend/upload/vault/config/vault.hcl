# backend/upload/vault/config/vault.hcl
#
# Vault server configuration for the OpenMates Upload Server.
# Production mode with file storage so secrets survive container restarts.
# TLS is terminated by Caddy — Vault only listens on the internal Docker network.

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

storage "file" {
  path = "/vault/file"
}

api_addr       = "http://0.0.0.0:8200"
ui             = false
disable_mlock  = true
log_level      = "info"
