---
status: active
doc_type: index
audience:
  - technical-users
last_verified: 2026-06-11
claims:
  - id: self-hosting-readme-links-core-guides
    type: unit
    claim: The self-hosting index links to setup, server hardening, and Proton Bridge guides.
    source:
      - docs/self-hosting/README.md
    test:
      file: scripts/tests/test_self_hosting_docs_claims.py
      command: python3 -m pytest scripts/tests/test_self_hosting_docs_claims.py
      assertion: self-hosting-readme-links-core-guides
    verified: '2026-06-11'
---

# Self-Hosting

Run your own OpenMates instance with full control over your data and infrastructure.

## Guide

- [Setup & Installation](setup.md) - CLI-first guide for installing and starting OpenMates on your own server
- [Server Hardening](server-hardening.md) - Six baseline protections every public-facing OpenMates server should have
- [Proton Mail Bridge](proton-bridge.md) - Connect a Proton Mail account for the mail search skill

The setup guide covers:

- Prerequisites and system requirements
- Installing the CLI with `npm install -g openmates`
- Running `openmates server install`
- Starting the backend and web app with `openmates server start`
- Signup modes for invite codes, email-domain allowlists, or both
- Optional AI provider keys and no-key startup behavior
- Production deployment with Caddy reverse proxy
- Management commands
- Troubleshooting common issues

## Requirements

- A Linux server (Ubuntu/Debian recommended)
- Docker and Docker Compose
- Optional AI provider API key when you want AI chat/model processing
- A domain name (for production deployment)
