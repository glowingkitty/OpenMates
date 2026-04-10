---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Probar repositorio git"
description: "Clona un repositorio git y prueba si funciona."
lang: es
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Probar repositorio git

## Process

- si no se proporcionó, pedir al usuario la URL del repositorio github/gitlab
- si no se proporcionó, preguntar al usuario qué quiere probar / cuál es su caso de uso
- usar la habilidad para revisar issues si hay problemas críticos reportados recientemente con el repositorio
- si el proyecto está reportado como roto, preguntar si el usuario quiere continuar con las pruebas
- preguntar al usuario dónde clonar y probar el repositorio ¿nueva máquina? ¿github codespaces? ¿máquina local? etc.
- clonar el repositorio en la ubicación especificada
- leer la estructura de carpetas y archivos del proyecto y readme.md para obtener una visión general
- descubrir cómo probar el proyecto y comenzar a probarlo
