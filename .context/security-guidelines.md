# Security Guidelines

## Table of Contents

- [Security Guidelines](#security-guidelines)
  - [Table of Contents](#table-of-contents)
  - [1. Threat Modeling \& Attack Vectors](#1-threat-modeling--attack-vectors)
  - [2. Security Measures \& Countermeasures](#2-security-measures--countermeasures)
  - [3. Security Testing \& Monitoring](#3-security-testing--monitoring)
  - [4. Incident Response Plan (Outline)](#4-incident-response-plan-outline)

## 1. Threat Modeling & Attack Vectors

This section outlines potential security threats relevant to OpenMates. Measures to mitigate these are detailed in the following sections.

*   **Account Takeover:** Unauthorized access to user accounts via credential stuffing, phishing, session token theft, or 2FA bypass attempts.
*   **Data Breaches:** Unauthorized access, modification, or exfiltration of sensitive data, including user account information, chat content (despite encryption), or internal configuration. Potential vectors include API vulnerabilities, insecure Directus configuration/access, or infrastructure compromise.
*   **Automated Scans & Probes:** Malicious bots scanning for common vulnerabilities, exposed files (`.env`, `.git`, config files), sensitive paths, or open ports.
*   **Insecure Direct Object References (IDOR):** Users potentially accessing data (e.g., chats) belonging to other users by manipulating object IDs in requests.
*   **Input Injection / Cross-Site Scripting (XSS):** Malicious input (e.g., in chat messages, user profiles) being processed or rendered insecurely, potentially leading to code execution in browsers or backend systems.
*   **Prompt Injection:** Malicious input designed to manipulate the behavior of underlying Large Language Models (LLMs) used by digital teammates.
*   **Denial of Service (DoS/DDoS):** Overwhelming system resources through excessive traffic, expensive API calls (especially to third-party AI services), or resource exhaustion attacks.
*   **Third-Party Risks:** Vulnerabilities within dependencies (software libraries), or security incidents affecting essential service providers (hosting, databases, AI services).
*   **Insecure Development/Management Access:** Unauthorized access to development servers, code repositories, or administrative interfaces like `code-server` or Directus.

## 2. Security Measures & Countermeasures

These measures should be implemented and maintained to mitigate the identified threats.

*   **Authentication & Session Management:**
    *   Implement Multi-Factor Authentication (MFA) using OTP as mandatory for all users.
    *   Securely manage session tokens (e.g., JWTs with short expiry, HTTPS-only cookies, refresh tokens).
    *   Implement device fingerprinting checks for logins and session renewals. Require re-authentication with 2FA OTP (not backup code) for unrecognized devices.
    *   Securely handle backup code generation, storage, and usage, with user notifications upon use.
    *   **Admin Account Security:** Implement stricter controls for administrator accounts:
        *   Disable administrative privileges/views if the session was initiated using a backup code.
        *   Send email notifications to the administrator for *every* successful login event.
        *   Strictly enforce device binding: If an admin session token is detected being used from a new/unrecognized device fingerprint, immediately invalidate the session and require full re-authentication. Notify the admin via email of the attempt.
*   **Admin Web Interface Security:**
    *   The administrative web interface is strictly limited in scope: managing software updates, viewing server performance/monitoring data (Grafana details, user counts, response times, security events), and managing invite/gift card codes.
    *   It explicitly **does not** provide access to sensitive user data (e.g., chat content), other users' information, or critical secrets like encryption keys or API keys managed in Vault.
    *   All administrative actions performed via the web interface (e.g., code generation) trigger email notifications to administrators, including options to reverse the action where applicable.
    *   Generated gift card codes have a built-in activation delay (e.g., 5 minutes) as an additional security measure.
    *   Management of critical secrets (e.g., adding/overwriting API keys in Vault) **must** be performed via secure SSH access to the server and dedicated CLI tools, not through the web interface.
*   **Authorization & Access Control:**
    *   **IDOR Prevention:** Implement strict authorization checks on **every** data access request. Verify that the authenticated user has explicit permission to access the specific resource identified by any user-provided ID. Check ownership before returning or modifying data. Return a generic "Either this doesn't exist or you don't have access." message (without revealing resource existence) if authorization fails.
*   **Input Sanitization & Validation:**
    *   **Backend Validation:** Rigorously validate and sanitize **all** input received from clients or external sources on the backend before processing or storing.
    *   **XSS Prevention:** Use robust libraries (e.g., DOMPurify frontend, Bleach backend) to sanitize any user-generated content (like chat messages) before rendering it as HTML. Treat all user input as untrusted.
    *   **Prompt Engineering:** Pre-process all incoming chat messages to check for prompt injection attempts and other malicious patterns. Only validated messages should be forwarded to the underlying LLMs. Implement defenses against prompt injection within the LLM interaction itself where feasible (e.g., instruction defense, output parsing).
*   **API & Edge Security (Caddy/WAF/Fail2Ban):**
    *   **Web Application Firewall (WAF):** Utilize WAF capabilities (e.g., Caddy features, Cloudflare, ModSecurity) to filter known malicious request patterns, common web attacks, and probes for sensitive files/paths (e.g., `/.env`, `/.git`).
    *   **Rate Limiting:** Implement strict rate limiting on API endpoints (in Caddy and/or FastAPI) to prevent brute-force attacks and mitigate DoS risks. Configure Caddy/Fail2Ban to rate limit or block IPs generating excessive 404 errors. Pay special attention to limiting expensive operations (e.g., AI service calls).
    *   **Secure Routing:** Configure Caddy to only expose necessary API endpoints and serve static files only from designated safe directories. Explicitly block requests for sensitive files or paths at the edge.
    *   **Fail2Ban:** Deploy Fail2Ban to monitor logs (Caddy, FastAPI, SSH) and automatically block IPs exhibiting malicious behavior (e.g., repeated 404s, failed logins, WAF triggers).
    *   **Origin Restriction:** Configure API gateways (e.g., Caddy) or backend frameworks to enforce strict origin checks for sensitive or web-app-exclusive endpoints, rejecting requests from unauthorized origins.
*   **Infrastructure Security:**
    *   **Firewalls:** Use host-based firewalls (`ufw`) and network firewalls (e.g., Hetzner Firewall) to restrict access to necessary ports only. Block all default-deny.
    *   **Network Segmentation (Production):** **Mandatory for Production.** Only the REST API server(s) are exposed directly to the internet. All other internal core services (Directus, Grafana, Celery, Database, Vault, etc.) reside on separate servers connected via a private virtual network (e.g., Hetzner vSwitch) and are *not* exposed externally. Communication between the API server and internal services occurs exclusively over this private network, secured by strict firewall rules (e.g., Hetzner Cloud Firewall) allowing only necessary ports (e.g., API VM to Directus/Vault ports). This significantly limits the attack surface and blast radius.
    *   **Server Hardening:** Follow standard server hardening practices (minimal software installation, regular OS/package updates, disable unused services, secure SSH configuration - e.g., key-based auth only, disable root login).
    *   **Secure Management Access (Dev/Prod):** Restrict access to sensitive management interfaces (`code-server`, Directus admin, Grafana, **Vault UI on Dev**) using a **VPN (e.g., Tailscale, WireGuard)** combined with firewall rules allowing access only from the VPN's private IP range. Avoid exposing these interfaces directly to the public internet.
    *   **Development Environment Access:** Access to sensitive services within the development environment is strictly limited to connections made via **Tailscale**.
    *   **Container Security:** Run applications inside containers as non-root users. Use minimal base images. Apply resource limits (CPU, memory). Isolate containers for high-risk tasks (code execution, web browsing) using separate servers and potentially stronger isolation mechanisms (e.g., gVisor).
    *   **Development Server Security:** **Never run development servers (`pnpm dev`, etc.) bound to public IPs.** Always build static frontend assets and serve them via a hardened web server like Caddy, even on internet-facing development/staging environments.
    *   **Software Updates & Patching:** Implement a process for regularly updating OS, services (Caddy, Directus, etc.), and application dependencies. Use a staging environment (e.g., the Dev server) to test updates before deploying to production. Consider blue/green or canary deployment strategies for production updates to minimize downtime and allow rollbacks.
*   **Data Encryption:**
    *   **At Rest:** Encrypt sensitive user data in the database using user-specific keys. Encrypt individual chats with chat-specific keys. Encrypt backups and archived logs.
    *   **In Transit:** Enforce TLS 1.2+ for all communication (HTTPS for web traffic, secure connections to databases and other services). Use Caddy for automated TLS certificate management.
*   **Secrets Management:**
    *   **Central Store:** Use **HashiCorp Vault** as the central, secure store for all application secrets (API keys, database credentials, service tokens, etc.).
    *   **Runtime Fetching:** Applications MUST fetch necessary secrets from Vault at runtime (e.g., during startup) after authenticating to Vault (e.g., via AppRole or other secure method). Secrets should be injected into the application environment (e.g., as environment variables) rather than being stored in configuration files or code.
    *   **Eliminate `.env` Files:** Avoid using `.env` files for storing secrets in the repository or on servers. The goal is to manage secrets exclusively through Vault.
    *   **Admin Management via App:** Implement a dedicated, highly secured administrative section within the main web application for managing *service-level* secrets (e.g., third-party API keys).
        *   Access requires strong administrator authentication.
        *   Modifying secrets MUST require additional verification steps (e.g., standard 2FA OTP plus an email-based OTP).
        *   The backend API endpoints handling these requests must perform rigorous authorization checks and securely interact with Vault using an appropriately permissioned Vault token.
        *   User-specific secrets (like data encryption keys) MUST NOT be accessible via this interface.
    *   **Bootstrapping:** Initial seeding of essential secrets into Vault might require temporary direct access via secure methods (e.g., Vault UI/CLI via VPN on dev environment). The initial Vault token required by the API service itself is generated by the `vault-setup` container.
        *   *Single-Host Setup (e.g., Dev):* The API service typically reads this token via a shared Docker volume (e.g., configured in `docker-compose.yml`).
        *   *Multi-VM Setup (e.g., Prod):* A secure mechanism is required to transfer the initial token from the Vault/Internal VM to the API VM (e.g., manual secure copy during setup) or implement Vault Agent on the API VM with an appropriate authentication method (e.g., AppRole) to avoid transferring the primary token.
*   **Dependency Management:**
    *   Regularly scan dependencies for known vulnerabilities using automated tools (e.g., Snyk, Dependabot, `pip-audit`) integrated into CI/CD.
    *   Update vulnerable dependencies promptly based on risk assessment.
*   **Third-Party Risk Management:**
    *   Perform due diligence when selecting third-party service providers, reviewing their security practices.
    *   Have Data Processing Agreements (DPAs) in place where required by GDPR.
    *   Apply the principle of least privilege when configuring integrations or granting API keys.
    *   Monitor provider status and security bulletins.
*   **Billing & Credit System Security:**
    *   Ensure accurate calculation and deduction of credits based on usage.
    *   Implement robust server-side validation to prevent unauthorized manipulation of user credit balances. Credits should only be modifiable through verified purchase transactions, the valid usage of gift card codes, or the use of invite codes with starting credits.


## 3. Security Testing & Monitoring

*   **Static Analysis (SAST):** Utilize linters with security plugins (e.g., Ruff, ESLint security rules) and potentially dedicated SAST tools (e.g., Bandit for Python, Semgrep) to identify potential vulnerabilities in code. Integrate into CI/CD.
*   **Dynamic Analysis (DAST):** Consider periodic manual or automated scanning of the running application using tools like OWASP ZAP or Burp Suite (Community Edition) to identify runtime vulnerabilities, especially after significant changes.
*   **Dependency Scanning:** Integrate automated scanning (Snyk, Dependabot, `pip-audit`) into the CI/CD pipeline and configure alerts for high-severity vulnerabilities.
*   **Secret Scanning:** Integrate tools like `gitleaks` into CI/CD to prevent accidental commits of secrets.
*   **Penetration Testing:** Consider periodic penetration testing by external experts as the application matures, before major launches, or if handling highly sensitive data.
*   **Security Monitoring & Alerting:**
    *   Monitor security-focused logs in Loki/Grafana for suspicious patterns (failed logins, errors, WAF blocks, 404 spikes).
    *   Configure alerts for critical security events (e.g., high rate of failed logins, WAF critical blocks, Fail2Ban actions, critical vulnerabilities detected, failed attempts to access admin secret management endpoints, **admin login notifications**, **admin session rejection due to new device**).
    *   Monitor alerts from Fail2Ban, WAFs, and dependency scanning tools.
    *   **Log Aggregation:** Utilize **Promtail** to collect logs from all internal services (Directus, Celery, Vault, etc.) on the private network and forward them securely to the central Loki instance for monitoring in Grafana.

## 4. Incident Response Plan (Outline)

*(This section provides a basic structure; a detailed plan should be developed separately).*

*   **Preparation:** Maintain up-to-date contact lists, documentation (including these guidelines, network diagrams), access credentials (securely stored), and necessary tools (e.g., backup access, forensic tools). Define roles and responsibilities for incident handling.
*   **Identification:** Detect incidents through monitoring, alerts, user reports, or external notifications. Assess the scope and severity quickly.
*   **Containment:** Isolate affected systems (e.g., using firewall rules, shutting down services), block malicious IPs (via WAF/Fail2Ban/Firewall), revoke potentially compromised credentials (API keys, user sessions), preserve evidence (logs, system snapshots).
*   **Eradication:** Identify and remove the root cause (e.g., patch vulnerabilities, remove malware, correct misconfigurations).
*   **Recovery:** Restore affected systems from secure backups, validate system integrity, monitor closely for residual issues.
*   **Post-Mortem:** Analyze the incident, document root cause, actions taken, lessons learned, and implement improvements to prevent recurrence. Fulfill any legal/regulatory notification requirements (e.g., GDPR breach notification within 72 hours if applicable).