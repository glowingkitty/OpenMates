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
  # sensitive   = true
}

variable "nginx_port" {
  description = "Nginx port for Grafana"
  type        = number
  default     = 8080
}

variable "grafana_install_dir" {
  description = "Installation directory for Grafana"
  type        = string
  default     = "grafana"
}

variable "deploy_env" {
  description = "Deployment environment (development/production)"
  type        = string
  default     = "development"
}

variable "standalone" {
  description = "Whether Grafana is being deployed standalone or as part of apps server"
  type        = bool
  default     = true
}

variable "app_hosting_grafana_admin_password" {
  description = "Admin password for Grafana"
  type        = string
  sensitive   = true
}

variable "app_hosting_grafana_install" {
  description = "Whether to install Grafana"
  type        = bool
  default     = true
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