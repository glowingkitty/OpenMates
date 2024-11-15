# variables.tf

# Variables for Hetzner Cloud and Plane configuration
variable "hcloud_token" {
  description = "API token for Hetzner Cloud"
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Domain name for Plane installation"
  type        = string
}

variable "admin_email" {
  description = "Email for SSL certificate registration"
  type        = string
  # sensitive   = true
}

variable "nginx_port" {
  description = "Nginx port for Plane"
  type        = number
  default     = 8080
}

variable "plane_install_dir" {
  description = "Installation directory for Plane"
  type        = string
  default     = "plane-selfhost"
}

variable "deploy_env" {
  description = "Deployment environment (development/production)"
  type        = string
  default     = "development"
}

variable "standalone" {
  description = "Whether Plane is being deployed standalone or as part of apps server"
  type        = bool
  default     = true
}
