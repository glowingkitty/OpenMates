# variables.tf

# Variables for Hetzner Cloud and Apps Server configuration
variable "hcloud_token" {
  description = "API token for Hetzner Cloud"
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Base domain name for all apps (e.g., openmates.org)"
  type        = string
}

variable "admin_email" {
  description = "Email for SSL certificate registration"
  type        = string
}

variable "nginx_port" {
  description = "Default Nginx port"
  type        = number
  default     = 8080
}

variable "deploy_env" {
  description = "Deployment environment (development/production)"
  type        = string
  default     = "development"
}

# New variable to control installation of plane and nginx roles
variable "app_project_management_plane_install" {
  description = "Flag to determine if the Plane and Nginx roles should be installed"
  type        = bool
  default     = false
}

# Map of applications with their subdomains and ports
variable "applications" {
  description = "Map of applications with their subdomains and corresponding ports"
  type = map(object({
    subdomain = string
    port      = number
  }))
  default = {
    plane = {
      subdomain = "apps-projectmanagement-plane.openmates.org"
      port      = 8081
    }
    # Add other applications here
  }
}
