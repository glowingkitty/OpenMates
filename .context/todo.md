# Todo List

## Table of Contents

- [Milestones](#milestones)
- [Milestone Descriptions](#milestone-descriptions)
- [Tasks](#tasks)
- [Task Descriptions](#task-descriptions)

## Milestones

| ID | Title               | Target Date | Tasks        | Status      |
|----|---------------------|-------------|--------------|-------------|
| M1 | Secure Dev Server   | 2025-04-10  | T1, T2, T3   | todo        |
| M2 | Launch First Version| 2025-04-21  | T4, T5, T6, T7 | todo        |

## Milestone Descriptions

### M1 - Secure Dev Server
Set up the development server with proper security configurations, including Caddy hardening, VPN access for sensitive services, and appropriate firewall rules.

### M2 - Launch First Version
Prepare the first version of the software for launch. This includes finishing the user signup flow (payment processing), fixing critical bugs (like 2FA), implementing the core chat backend logic, and enabling chat persistence on the client-side.

## Tasks

| ID | Title                                                 | Priority | Status | Depends on | Milestone | Tags                     |
|----|-------------------------------------------------------|----------|--------|------------|-----------|--------------------------|
| T1 | Configure Caddy security measures                     | High     | todo   | -          | M1        | security, devops, caddy  |
| T2 | Set up VPN for secure access                          | High     | todo   | -          | M1        | security, devops, vpn    |
| T3 | Restrict sensitive service access via VPN/firewall    | High     | todo   | T2         | M1        | security, devops, firewall |
| T4 | Implement Revolut payment processing for signup       | High     | todo   | M1         | M2        | backend, payments, signup|
| T5 | Investigate and fix 2FA bug (encryption/Vault related)| High     | todo   | M1         | M2        | backend, bugfix, auth, 2fa |
| T6 | Implement backend chat logic (API, Celery, LLM)       | High     | todo   | M1         | M2        | backend, chat, llm, api  |
| T7 | Implement chat creation/loading (frontend offline)    | High     | todo   | M1         | M2        | frontend, chat, offline  |

## Task Descriptions

### T1 - Configure Caddy security measures
Review and implement security best practices for the Caddy reverse proxy configuration on the development server. This includes setting appropriate headers, configuring rate limiting, potentially setting up basic WAF rules, and ensuring TLS is properly configured.

### T2 - Set up VPN for secure access
Install and configure a VPN solution (e.g., Tailscale, WireGuard) on the development server to provide secure, restricted access to internal management interfaces and services.

### T3 - Restrict sensitive service access via VPN/firewall
Configure firewall rules (e.g., ufw, Hetzner Firewall) on the development server to ensure that sensitive services (like Directus UI, Grafana, Vault UI, code-server) are only accessible via the VPN connection (using VPN client IP ranges).

### T4 - Implement Revolut payment processing for signup
Integrate the Revolut Business Merchant API into the user signup flow to handle payment processing for subscriptions or credits. This involves backend API endpoints, communication with Revolut, and updating the frontend UI.

### T5 - Investigate and fix 2FA bug (encryption/Vault related)
Diagnose the root cause of the bug preventing users from setting up 2FA. Investigate potential issues related to user data encryption/decryption processes, interactions with HashiCorp Vault, or the 2FA setup logic itself. Implement a fix.

### T6 - Implement backend chat logic (API, Celery, LLM)
Develop the backend components required for the chat functionality. This includes:
- API endpoints to receive messages from the frontend.
- Forwarding messages to a Celery task queue for asynchronous processing.
- Implementing pre-processing steps for the messages.
- Integrating with the chosen Large Language Model (LLM) API.
- Returning the LLM response back to the frontend via the API.

### T7 - Implement chat creation/loading (frontend offline)
Implement the frontend logic for creating new chat sessions and loading existing chats. Ensure that chat history is saved locally on the user's device (e.g., using IndexedDB or similar) to allow for offline access.