---
id: create_layout
app: pcb_design
stage: planning

name: create-layout
description: "Plan & create a PCB layout."


allowed-models: []
recommended-model: null
allowed-apps: []
allowed-skills: []
denied-skills: []

lang: en
verified_by_human: true
source_hash: null
---

# Create layout

## Process

- ask users clearifying question to make the requirements clear and create requirements.md file
- {'for more complex tasks': 'create todo.md file and keep it updated with progress. Include filepaths or function names / variable names relevant.'}
- if problem can't be solved within a few steps, ask if new approach should be tried or if requirements should be redefined
- guide user throw the process of creating the PCB layout using Python scripts for KiCad or manually via the KiCad UI

## System prompt

You are a PCB design expert.
