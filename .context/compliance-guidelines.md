# Compliance Guidelines

## Table of Contents

- [Compliance Guidelines](#compliance-guidelines)
  - [Table of Contents](#table-of-contents)
  - [1. Regulatory Landscape](#1-regulatory-landscape)
  - [2. Compliance Logging Requirements](#2-compliance-logging-requirements)
  - [3. Data Handling Procedures](#3-data-handling-procedures)
  - [4. Compliance Audits \& Certifications](#4-compliance-audits--certifications)

## 1. Regulatory Landscape

*   **Primary Regulation:** The General Data Protection Regulation (**GDPR**) is the primary compliance framework governing the handling of personal data for users within the European Union. All data processing activities must adhere to its principles.
*   **Core Principles Applied:**
    *   **Data Minimization:** Collect and store only the minimum personal data absolutely necessary for providing the service. Sensitive data in the database (beyond essential account info) should be encrypted using user-specific keys.
    *   **Purpose Limitation:** Personal data collected should only be used for the specific purposes communicated to the user.
    *   **Storage Limitation:** Do not keep personal data longer than necessary (see Logging and Data Handling sections).
    *   **Integrity & Confidentiality:** Implement strong security measures (encryption, access controls) to protect personal data.
    *   **Client-Side Processing:** Whenever feasible without compromising security or essential functionality, prefer processing data directly on the user's device (client-side) rather than sending it to the server. This further minimizes data transmission and server-side storage (e.g., client-side search within user's own chat history).
*   **Data Sovereignty & Processing:**
    *   Prioritize using EU-based or self-hosted services for all data processing, especially for potentially sensitive information shared in chats.
    *   Avoid sending identifiable personal data to third-party services (especially non-EU based) whenever feasible. Explore techniques like replacing sensitive entities (e.g., file paths, names, addresses) with placeholders before sending data to external APIs (like LLMs) and re-inserting the original data upon return, where this doesn't compromise functionality. Evaluate feasibility on a case-by-case basis.
*   **Other Regulations:** While GDPR is the focus, remain aware of other potential regulations (e.g., CCPA) if targeting users in specific regions outside the EU. German commercial and tax laws (e.g., HGB, AO) also apply regarding retention of business records.

## 2. Compliance Logging Requirements

*   **Purpose:** To provide an audit trail for security incident investigation, enable operational security responses (e.g., IP blocking), and potentially demonstrate compliance. Logs should balance security needs with the principle of data minimization.
*   **Events Logged (Security Focus):** Specific security-sensitive events MUST be logged for compliance and operational security purposes. These include:
    *   Failed login attempts.
    *   Successful login from a new/unrecognized device.
    *   Use of a backup code for login.
    *   Password change requests and completions.
    *   Email address change requests and completions.
    *   2FA setup/modification/removal.
    *   Account deletion requests.
    *   Data export requests.
    *   Significant changes to user permissions or roles (if applicable).
    *   *(Note: Successful logins from known/trusted devices are generally NOT logged for compliance purposes to minimize data collection).*
*   **Log Content (Security Events):** For the specific security events listed above, logs should include:
    *   Timestamp (UTC).
    *   User ID (if applicable).
    *   Event type/description.
    *   Outcome (success/failure).
    *   **IP Address:** Log the **raw IP address** during short-term retention for operational security. See Storage & Retention below.
    *   Device Fingerprint Hash.
*   **Log Content (Other Events):** For general application logs not related to the specific security events above, **DO NOT log IP addresses or derived location data**. Device fingerprint hashes should only be stored encrypted if needed for functionality (like identifying known devices).
*   **Storage & Retention:**
    *   **Short-Term (Operational/Security Monitoring - Loki/Grafana):** Security-relevant compliance logs containing the **raw IP address** and device hash are sent to Loki/Grafana for immediate monitoring and operational response (e.g., IP blocking) for approximately **4 days**.
    *   **Long-Term (Compliance Archive - Object Storage):** After the initial ~4-day period, these specific security logs are moved to secure, encrypted, EU-based object storage (e.g., Hetzner S3 or similar). During this archival process, the **raw IP address MUST be hashed** (using a consistent, salted method suitable for correlation) to minimize long-term storage of raw IPs while still allowing source correlation. Access to the archive should be strictly controlled (read-only for authorized personnel). Logs (with hashed IP) are retained in the archive for **1 year** and then automatically deleted. *(Rationale: This balances immediate operational security needs with the GDPR principle of data minimization for long-term storage).*
    *   **Financial Records:** Business records, especially **invoices**, must be retained according to German commercial and tax law (HGB/AO), which typically requires **10 years**. These records should be stored securely (e.g., encrypted on Hetzner S3 with backups). *(Disclaimer: Verify specific legal retention periods with official sources or legal counsel).*
*   **Log Format:** Use a consistent, structured format (e.g., JSON) for all logs to facilitate parsing and analysis.

## 3. Data Handling Procedures

*   **Data Inventory:** Maintain an internal inventory mapping what personal data is collected, where it's stored (e.g., Directus database, object storage), why it's collected, and its retention period. *(Status: To be formally documented)*.
*   **Data Retention & Deletion:**
    *   User account data is retained while the account is active. Define policy for inactive account deletion (e.g., after [Y months/years] of inactivity). *(Status: Policy TBD)*.
    *   **Chat Data:** Implement a default retention period of **6 months** for user chat messages. Data older than this period should be automatically and securely deleted. Provide users with clear options in the **settings menu** to configure a different (e.g., shorter) retention period. Clearly communicate this default and the available options to the user.
    *   Implement robust procedures for securely deleting user data upon verified request or account closure, including data held by third-party processors where applicable.
*   **Third-Party Data Sharing:**
    *   Minimize sharing of personal data with third parties.
    *   Only share data with essential providers (preferably EU-based or self-hosted) listed transparently.
    *   **In-Context Notification:** Clearly inform the user *before* their data is shared with a third-party service, explaining what data is shared, with whom, and why. Provide clear links to the third party's privacy policy.
    *   Maintain internal documentation (e.g., a structured file like `privacy_policy.yml`) tracking key data processing aspects and identified potential risks from third-party providers for transparency. Always refer users to the provider's official policy as the definitive source. Consider implementing features allowing users to ask their digital teammate for on-demand explanations of linked third-party policies.
*   **Privacy Policy:** Maintain an up-to-date, clear, and comprehensive privacy policy accessible to users. Consider using a structured source (e.g., `privacy_policy.yml`) to manage content and facilitate generation/translation.

## 4. Compliance Audits & Certifications

*   **External Audits:** Formal external compliance audits or certifications are not currently planned.
*   **Internal Reviews:** Conduct periodic internal reviews (e.g., annually) of data handling practices, security measures, and documentation against these guidelines and GDPR principles to ensure ongoing compliance and identify areas for improvement.