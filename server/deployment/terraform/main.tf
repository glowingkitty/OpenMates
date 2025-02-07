# main.tf

terraform {
  required_providers {
    hcloud = {
      source = "hetznercloud/hcloud"
      version = "~> 1.45.0"
    }
  }
}

# Define the Hetzner provider
provider "hcloud" {
  token = var.hcloud_token
}

# Reference existing SSH key instead of creating a new one
data "hcloud_ssh_key" "existing_key" {
  name = "openmates-ssh-key"
}

# Hetzner Cloud ARM (Ampere) Server Types
# +--------+-------+--------+---------+-----------+-------------+----------------+
# | TYPE   | vCPUs | RAM    | SSD     | TRAFFIC   | PRICE/HOUR  | PRICE/MONTH   |
# +--------+-------+--------+---------+-----------+-------------+----------------+
# | CAX11  | 2     | 4 GB   | 40 GB   | 20 TB     | €0.005/h    | €3.29/mo      |
# | CAX21  | 4     | 8 GB   | 80 GB   | 20 TB     | €0.010/h    | €5.99/mo      |
# | CAX31  | 8     | 16 GB  | 160 GB  | 20 TB     | €0.019/h    | €11.99/mo     |
# | CAX41  | 16    | 32 GB  | 320 GB  | 20 TB     | €0.038/h    | €23.99/mo     |
# +--------+-------+--------+---------+-----------+-------------+----------------+
#
# Additional costs:
# - IPv4: €0.0008/h per IP (approximately €0.60/month)
# - Backups: +20% of server price
#   * CAX11 backup cost: €0.001/h (€0.66/mo)
#   * CAX21 backup cost: €0.002/h (€1.20/mo)
#   * CAX31 backup cost: €0.0038/h (€2.40/mo)
#   * CAX41 backup cost: €0.0076/h (€4.80/mo)
# Total cost for CAX31 with IPv4 and backups:
# €0.019/h (server) + €0.0008/h (IPv4) + €0.0038/h (backup) = €0.0236/h (approximately €14.99/month)

# Define servers on Hetzner
resource "hcloud_server" "app_servers" {
  # Create a map of servers with their configurations
  for_each = {
    # Server for the OpenMates Web App
    # webapp = {
    #   name = "webapp-server"
    #   type = "cax11"
    # }
    # Server for the Apps which can run locally and which OpenMates can control
    apps = {
      name = "apps-server"
      type = "cax31"
    }
  }

  name        = each.value.name
  image       = "ubuntu-20.04"
  server_type = each.value.type
  location    = "fsn1"
  ssh_keys    = [data.hcloud_ssh_key.existing_key.id]
  backups     = true  # Enable automated backups
}

# Generate Ansible inventory for all servers
resource "local_file" "ansible_inventory" {
  content = templatefile("${path.module}/templates/inventory.tpl", {
    # webapp_ip = hcloud_server.app_servers["webapp"].ipv4_address
    apps_ip = hcloud_server.app_servers["apps"].ipv4_address
  })
  filename = "${path.module}/../ansible/inventory/hosts.yml"
}

# SSH setup for all servers
resource "null_resource" "ssh_setup" {
  for_each = hcloud_server.app_servers

  provisioner "local-exec" {
    command = <<-EOT
      mkdir -p ~/.ssh
      for i in {1..30}; do
        if ssh-keyscan -H ${each.value.ipv4_address} >> ~/.ssh/known_hosts 2>/dev/null; then
          echo "Successfully added host key for ${each.value.name}"
          if ssh -o ConnectTimeout=5 -i ~/.ssh/hetzner_key_openmates root@${each.value.ipv4_address} 'echo "SSH connection successful"'; then
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

# Run Ansible playbook with Terraform variables
resource "null_resource" "ansible_provisioner" {
  depends_on = [
    hcloud_server.app_servers,
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
          app_project_management_plane_install='${var.app_project_management_plane_install}'
        " \
        site.yml
    EOT
  }

  triggers = {
    # webapp_server_id = hcloud_server.app_servers["webapp"].id
    apps_server_id      = hcloud_server.app_servers["apps"].id
    inventory_content   = local_file.ansible_inventory.content
    domain_name         = var.domain_name
    admin_email         = var.admin_email
    nginx_port          = var.nginx_port
    deploy_env          = var.deploy_env
    app_project_management_plane_install = var.app_project_management_plane_install
  }
}

# Define firewall rules for apps server
resource "hcloud_firewall" "apps_firewall" {
  name = "apps-firewall"

  # SSH access
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = ["0.0.0.0/0"]
  }

  # HTTP access
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = ["0.0.0.0/0"]
  }

  # HTTPS access
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = ["0.0.0.0/0"]
  }

  # Add additional ports as needed for other apps
  # rule {
  #   direction   = "in"
  #   protocol    = "tcp"
  #   port        = "other_port"
  #   source_ips  = ["0.0.0.0/0"]
  # }
}

# Apply firewall to apps server
resource "hcloud_firewall_attachment" "apps_firewall" {
  firewall_id = hcloud_firewall.apps_firewall.id
  server_ids  = [hcloud_server.app_servers["apps"].id]
}

# Output both server IPs
output "server_ips" {
  value = {
    # webapp_ip = hcloud_server.app_servers["webapp"].ipv4_address
    apps_ip = hcloud_server.app_servers["apps"].ipv4_address
  }
}