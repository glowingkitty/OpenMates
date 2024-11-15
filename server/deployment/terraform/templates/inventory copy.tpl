all:
  children:
    webapp:
      hosts:
        webapp-01:
          ansible_host: ${webapp_ip}
          ansible_user: root
    apps:
      hosts:
        apps-01:
          ansible_host: ${apps_ip}
          ansible_user: root
