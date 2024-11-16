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

# Define the server on Hetzner
resource "hcloud_server" "plane_server" {
  name        = "plane-server"
  image       = "ubuntu-20.04"
  server_type = "cax11"
  location    = "fsn1"
  ssh_keys    = [data.hcloud_ssh_key.existing_key.id]
}

# Generate Ansible inventory
resource "local_file" "ansible_inventory" {
  content = templatefile("${path.module}/templates/inventory.tpl", {
    server_ip = hcloud_server.plane_server.ipv4_address
  })
  filename = "${path.module}/../ansible/inventory/hosts.yml"
}

# Fetch server information including SSH host key
data "hcloud_server" "plane_server_info" {
  depends_on = [hcloud_server.plane_server]
  id         = hcloud_server.plane_server.id
}

# Add server's host key to known_hosts and ensure SSH is accessible
resource "null_resource" "ssh_setup" {
  depends_on = [hcloud_server.plane_server]

  provisioner "local-exec" {
    command = <<-EOT
      mkdir -p ~/.ssh
      for i in {1..30}; do
        if ssh-keyscan -H ${hcloud_server.plane_server.ipv4_address} >> ~/.ssh/known_hosts 2>/dev/null; then
          echo "Successfully added host key"
          # Test SSH connection
          if ssh -o ConnectTimeout=5 -i ~/.ssh/hetzner_key_openmates root@${hcloud_server.plane_server.ipv4_address} 'echo "SSH connection successful"'; then
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
    hcloud_server.plane_server,
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
      PLANE_STANDALONE="${var.standalone}" \
      ansible-playbook \
        -i inventory/hosts.yml \
        --private-key=~/.ssh/hetzner_key_openmates \
        site.yml
    EOT
  }

  # Modified triggers to avoid file hash calculation before file exists
  triggers = {
    server_id = hcloud_server.plane_server.id
    # Using the content of the inventory file instead of its hash
    inventory_content = local_file.ansible_inventory.content
  }
}

output "server_ip" {
  value = hcloud_server.plane_server.ipv4_address
}