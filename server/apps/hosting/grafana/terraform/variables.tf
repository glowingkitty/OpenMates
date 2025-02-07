# Variables for Hetzner Cloud and Grafana configuration

variable "hcloud_token" {
  description = "API token for Hetzner Cloud"
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Domain name for Grafana installation"
  type        = string
}

variable "admin_email" {
  description = "Email for SSL certificate registration"
  type        = string
}

variable "nginx_port" {
  description = "Nginx port for Grafana"
  type        = number
  default     = 8080
}

variable "deploy_env" {
  description = "Deployment environment (development/production)"
  type        = string
  default     = "development"
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
      subdomain = "apps-plane.openmates.org"
      port      = 8081
    }
    # Add other applications here
  }
}

# New variable to control installation of plane and nginx roles
variable "app_hosting_grafana_install" {
  description = "Flag to determine if the Grafana and Nginx roles should be installed"
  type        = bool
  default     = false
}

variable "app_hosting_grafana_admin_password" {
  description = "Admin password for Grafana"
  type        = string
}


variable "app_hosting_grafana_admin_user" {
  description = "Admin user for Grafana"
  type        = string
}

variable "app_hosting_grafana_allow_signup" {
  description = "Allow signup for Grafana"
  type        = bool
}

variable "app_hosting_grafana_default_role" {
  description = "Default role for Grafana"
  type        = string
}

variable "app_hosting_grafana_basic_auth" {
  description = "Basic auth for Grafana"
  type        = bool
}