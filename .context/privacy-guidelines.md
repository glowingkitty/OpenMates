# Privacy Guidelines

## Table of Contents

- [Privacy Guidelines](#privacy-guidelines)
  - [Table of Contents](#table-of-contents)
  - [1. Introduction](#1-introduction)
  - [2. Guiding Privacy Principles](#2-guiding-privacy-principles)
  - [3. Data Collection Policy](#3-data-collection-policy)
  - [4. Sensitive Data Handling](#4-sensitive-data-handling)
  - [5. Third-Party Providers \& Data Sharing](#5-third-party-providers--data-sharing)
  - [6. User Rights \& Control](#6-user-rights--control)
  - [7. End-User Contact Methods](#7-end-user-contact-methods)

## 1. Introduction

OpenMates is deeply committed to protecting user privacy. We believe privacy is a fundamental right and strive to build a product that users trust and value. Our approach is centered around transparency, user control, and minimizing data collection. We are not in the business of data collection; we are focused on building the best product that users love and gain value from.

## 2. Guiding Privacy Principles

Our privacy practices are guided by the following core principles:

*   **Privacy by Design:** Privacy considerations are integrated into the design and development of our services from the outset.
*   **Data Minimization:** We collect and retain only the minimum amount of personal data necessary to provide and improve our services.
*   **Transparency:** We are clear and open about what data we collect, why we collect it, and how it is used. Our Privacy Policy and Terms of Conditions are written to be easily understandable.
*   **User Control:** We empower users with control over their data, including rights to access, modify, and delete their information.
*   **Security:** We implement robust technical and organizational measures to protect user data from unauthorized access, disclosure, alteration, or destruction.
*   **Purpose Limitation:** Data collected for a specific purpose will not be used for unrelated purposes without user consent.
*   **On-Device Processing:** Where reasonably feasible, data processing (like full-text search in chats and settings) will occur directly on the user's device to minimize data transmission and server-side storage.

## 3. Data Collection Policy

*   **What Data IS Collected (and Why):**
    *   **Account Information:** Basic details required for account creation and management (e.g., email address, hashed password, 2FA setup). Necessary for authentication and communication.
    *   **Usage Data:** Non-personally identifiable information about how users interact with the service (e.g., feature usage frequency). Used for service improvement and identifying issues.
    *   **Chat Content:** User conversations with digital teammates. Necessary for providing the core chat functionality. Stored encrypted.
    *   **Payment Information:** Details required by our payment processor (Revolut Business) when users make purchases. We do not store full payment card details ourselves. We only store a shortened/ anonymized version of the card number for invoice generation and billing settings overview of past purchases.
    *   **IP Address & Device Information:** Collected temporarily for security purposes (e.g., detecting suspicious logins, operational security). See Compliance Guidelines for retention details.
    *   **User-Uploaded Content:** Files or images uploaded by the user, potentially processed for moderation or specific features.
*   **What Data IS NOT Collected:**
    *   We strive to avoid collecting sensitive personal data unless strictly necessary for a specific feature explicitly requested by the user.
    *   We do not track users across third-party websites or services.
    *   We do not sell user data.

## 4. Sensitive Data Handling

*   **Encryption:** All sensitive user data, including chat content and account credentials, MUST be encrypted both at rest (in the database, using user-specific or chat-specific keys where appropriate) and in transit (using TLS 1.2+).
*   **Access Control:** Strict access controls are implemented to limit internal access to user data on a need-to-know basis.
*   **Data Replacement:** Before sending data containing potentially sensitive user information (e.g., names, locations within chat content) to external services (especially non-EU based AI providers), implement mechanisms to automatically replace sensitive entities with placeholders where feasible without compromising functionality. The original data should be re-inserted upon receiving the response.
*   **Logging:** Sensitive user data (e.g., chat content, passwords, full PII) MUST NOT be logged, except for specific security-relevant events outlined in the Compliance Guidelines (e.g., failed login attempts, account changes).
*   **Chat Data Retention:** User chat messages are automatically deleted after a default period of **6 months**. Users MUST be provided with clear options in their settings to configure a different (e.g., shorter) retention period.
*   **Account Security Notifications:** Users MUST be informed via email about security-sensitive account actions, such as logins from new devices, email change requests, or 2FA modifications.
*   **Mandatory 2FA:** Two-factor authentication (2FA) via OTP is mandatory for all users to enhance account security.

## 5. Third-Party Providers & Data Sharing

We utilize essential third-party services to provide our functionality. We only share the minimum data necessary with these providers. Users will be clearly informed *before* their data is shared with a third-party service, explaining what data is shared, with whom, and why, including links to the provider's privacy policy.

| Provider         | Purpose(s)                                      | Privacy Policy Link                                |
| :--------------- | :---------------------------------------------- | :------------------------------------------------- |
| Vercel           | Web app & website static frontend hosting       | https://vercel.com/legal/privacy-policy            |
| Hetzner          | Backend hosting, processing, database, S3 files | https://www.hetzner.com/legal/privacy-policy       |
| IP-API           | IP address geolocation                          | https://members.ip-api.com/privacy-policy        |
| Mailjet          | Email sending                                   | https://www.mailjet.com/privacy-policy           |
| Sightengine      | Moderation for uploaded images & videos         | https://sightengine.com/policies/privacy         |
| Revolut Business | Payment processing                              | https://www.revolut.com/privacy-policy           |
| *(AI Providers)* | *(e.g., Language model processing)*             | *(Specify providers & link policies when finalized)* |

*(Note: This list should be kept synchronized with `shared/docs/privacy_policy.yml` and updated as providers change. AI provider details need to be added once confirmed.)*

## 6. User Rights & Control

Users have the following rights regarding their personal data:

*   **Access:** Users can request access to the personal data we hold about them.
*   **Rectification:** Users can correct inaccurate or incomplete personal data.
*   **Erasure:** Users can request the deletion of their personal data, subject to legal retention requirements.
*   **Portability:** Users can request a copy of their data in a machine-readable format.
*   **Objection/Restriction:** Users can object to or request restrictions on certain types of data processing.

These rights can typically be exercised through account settings or by contacting support.

## 7. End-User Contact Methods

For questions or concerns regarding privacy, users can:

1.  Ask their **digital teammates** within the application. The teammates can provide information based on our policies or escalate the query to the human support team if necessary.
2.  Contact support directly via email at support email address