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

# Define SSH key to access the server
resource "hcloud_ssh_key" "my_key" {
  name       = "my_ssh_key"
  public_key = file("~/.ssh/hetzner_key_openmates.pub")
}

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
      type = "cax11"
    }
  }

  name        = each.value.name
  image       = "ubuntu-20.04"
  server_type = each.value.type
  location    = "fsn1"
  ssh_keys    = [hcloud_ssh_key.my_key.id]
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

# Run Ansible playbook with environment variables
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
      PLANE_DOMAIN="${var.domain_name}" \
      PLANE_ADMIN_EMAIL="${var.admin_email}" \
      PLANE_INSTALL_DIR="${var.plane_install_dir}" \
      NGINX_PORT="${var.nginx_port}" \
      DEPLOY_ENV="${var.deploy_env}" \
      ansible-playbook \
        -i inventory/hosts.yml \
        --private-key=~/.ssh/hetzner_key_openmates \
        site.yml
    EOT
  }

  triggers = {
    # webapp_server_id = hcloud_server.app_servers["webapp"].id
    apps_server_id = hcloud_server.app_servers["apps"].id
    inventory_content = local_file.ansible_inventory.content
  }
}

# Define firewall rules for apps server
resource "hcloud_firewall" "apps_firewall" {
  name = "apps-firewall"

  # SSH access
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = ["0.0.0.0/0"]
  }

  # HTTP access
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = ["0.0.0.0/0"]
  }

  # HTTPS access
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = ["0.0.0.0/0"]
  }

  # Add additional ports as needed for other apps
  # rule {
  #   direction = "in"
  #   protocol  = "tcp"
  #   port      = "other_port"
  #   source_ips = ["0.0.0.0/0"]
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
    # webapp = hcloud_server.app_servers["webapp"].ipv4_address
    apps = hcloud_server.app_servers["apps"].ipv4_address
  }
}