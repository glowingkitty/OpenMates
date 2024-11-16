all:
  hosts:
    grafana_server:
      ansible_host: ${server_ip}
      ansible_user: root
      ansible_python_interpreter: /usr/bin/python3
