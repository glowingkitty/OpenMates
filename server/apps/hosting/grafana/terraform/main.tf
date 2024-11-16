# main.tf

terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45.0"
    }
  }
}

# Define the Hetzner provider with the updated API token variable
provider "hcloud" {
  token = var.hcloud_token
}

# Reference existing SSH key instead of creating a new one
data "hcloud_ssh_key" "existing_key" {
  name = "openmates-ssh-key"
}

# Define the server on Hetzner
resource "hcloud_server" "grafana_server" {
  name        = "grafana-server"
  image       = "ubuntu-20.04"
  server_type = "cax11"
  location    = "fsn1"
  ssh_keys    = [data.hcloud_ssh_key.existing_key.id]
}

# Generate Ansible inventory using the updated server IP variable
resource "local_file" "ansible_inventory" {
  content  = templatefile("${path.module}/templates/inventory.tpl", {
    server_ip = hcloud_server.grafana_server.ipv4_address
  })
  filename = "${path.module}/../ansible/inventory/hosts.yml"
}

# Fetch server information including SSH host key
data "hcloud_server" "grafana_server_info" {
  depends_on = [hcloud_server.grafana_server]
  id         = hcloud_server.grafana_server.id
}

# Add server's host key to known_hosts and ensure SSH is accessible
resource "null_resource" "ssh_setup" {
  depends_on = [hcloud_server.grafana_server]

  provisioner "local-exec" {
    command = <<-EOT
      mkdir -p ~/.ssh
      for i in {1..30}; do
        if ssh-keyscan -H ${hcloud_server.grafana_server.ipv4_address} >> ~/.ssh/known_hosts 2>/dev/null; then
          echo "Successfully added host key"
          # Test SSH connection
          if ssh -o ConnectTimeout=5 -i ~/.ssh/hetzner_key_openmates root@${hcloud_server.grafana_server.ipv4_address} 'echo "SSH connection successful"'; then
            exit 0
          fi
        fi
        echo "Attempt $i: Waiting for SSH to become available..."
        sleep 10
      done
      echo "Failed to establish SSH connection after 30 attempts"
      exit 1
    EOT
  }
}

# Run Ansible playbook after server creation and SSH setup
resource "null_resource" "ansible_provisioner" {
  depends_on = [
    hcloud_server.grafana_server,
    local_file.ansible_inventory,
    null_resource.ssh_setup
  ]

  provisioner "local-exec" {
    command = <<-EOT
      cd ../ansible && \
      ANSIBLE_HOST_KEY_CHECKING=False \
      ansible-playbook \
        -i inventory/hosts.yml \
        --private-key=~/.ssh/hetzner_key_openmates \
        --extra-vars "
          domain_name='${var.domain_name}'
          admin_email='${var.admin_email}'
          nginx_port='${var.nginx_port}'
          deploy_env='${var.deploy_env}'
          app_hosting_grafana_install='${var.app_hosting_grafana_install}'
          app_hosting_grafana_admin_password='${var.app_hosting_grafana_admin_password}'
          app_hosting_grafana_admin_user='${var.app_hosting_grafana_admin_user}'
          app_hosting_grafana_allow_signup='${var.app_hosting_grafana_allow_signup}'
          app_hosting_grafana_default_role='${var.app_hosting_grafana_default_role}'
          app_hosting_grafana_basic_auth='${var.app_hosting_grafana_basic_auth}'
        " \
        site.yml
    EOT
  }

  # Modified triggers to avoid file hash calculation before file exists
  triggers = {
    server_id         = hcloud_server.grafana_server.id
    # Using the content of the inventory file instead of its hash
    inventory_content = local_file.ansible_inventory.content
  }
}

# Output the server IP address for reference
output "server_ip" {
  value = hcloud_server.grafana_server.ipv4_address
}