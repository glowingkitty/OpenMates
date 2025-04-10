# Todo List

When you start working on a task, always change the status from todo to 'in-progress'.

## Table of Contents

- [Milestones](#milestones)
- [Milestone Descriptions](#milestone-descriptions)
- [Tasks](#tasks)
- [Task Descriptions](#task-descriptions)

## Milestones

| ID | Title                             | Target Date | Tasks                                                              | Status      |
|----|-----------------------------------|-------------|--------------------------------------------------------------------|-------------|
| M1 | Secure Dev Server                 | 2025-04-10  | T1, T2, T3                                                         | todo        |
| M2 | Launch First Version              | 2025-04-21  | T4, T5, T6, T7                                                         | todo        |
| M3 | Infrastructure & Deployment       | -           | T8, T9, T10, T11                                                   | todo        |
| M4 | Core App Functionality            | -           | T12, T13, T14, T15, T16, T17, T18, T19, T20, T21, T22, T23, T24, T25 | todo        |
| M5 | Content, SEO & Internationalization | -           | T26, T27, T28, T29, T30, T31, T32, T33                               | todo        |
| M6 | Security, Safety & Compliance     | -           | T34, T35, T36, T37, T38, T39, T40, T41, T42, T43, T44, T45           | todo        |
| M7 | Monitoring, Testing & Reliability | -           | T46, T47, T48                                                      | todo        |
| M8 | AI & Model Management             | -           | T49, T50, T51, T52, T53, T54, T55                                   | todo        |
| M9 | Future Features & Enhancements    | -           | T56, T57                                                           | todo        |

## Milestone Descriptions

### M1 - Secure Dev Server
Set up the development server with proper security configurations, including Caddy hardening, VPN access for sensitive services, and appropriate firewall rules.

### M2 - Launch First Version
Prepare the first version of the software for launch. This includes finishing the user signup flow (payment processing), fixing critical bugs (like 2FA), implementing the core chat backend logic, and enabling chat persistence on the client-side.

### M3 - Infrastructure & Deployment
Focuses on hosting, deployment processes, monitoring, and infrastructure setup/security.

### M4 - Core App Functionality
Covers main user-facing features like PDF handling, UI generation, offline capabilities, chat improvements, settings, etc.

### M5 - Content, SEO & Internationalization
Tasks related to website content, discoverability, translations, and legal document generation.

### M6 - Security, Safety & Compliance
Addresses application security, content safety, user account security features, and compliance aspects.

### M7 - Monitoring, Testing & Reliability
Focuses on automated testing, system monitoring, and reliability checks.

### M8 - AI & Model Management
Tasks specifically related to integrating and managing different AI models.

### M9 - Future Features & Enhancements
Captures potential future additions like calendar integration and privacy options.

## Tasks

| ID | Title                                                                              | Priority | Status | Depends on | Milestone | Tags                                     |
|----|------------------------------------------------------------------------------------|----------|--------|------------|-----------|------------------------------------------|
| T1 | Configure Caddy security measures                                                  | High     | todo   | -          | M1        | security, devops, caddy                  |
| T2 | Set up VPN for secure access                                                       | High     | todo   | -          | M1        | security, devops, vpn                    |
| T3 | Restrict sensitive service access via VPN/firewall                                 | High     | todo   | T2         | M1        | security, devops, firewall             |
| T4 | Implement Revolut payment processing for signup                                    | High     | todo   | M1         | M2        | backend, payments, signup                |
| T5 | Investigate and fix 2FA bug (encryption/Vault related)                             | High     | todo   | M1         | M2        | backend, bugfix, auth, 2fa               |
| T6 | Implement backend chat logic (API, Celery, LLM)                                    | High     | todo   | M1         | M2        | backend, chat, llm, api                  |
| T7 | Implement chat creation/loading (frontend offline)                                 | High     | todo   | M1         | M2        | frontend, chat, offline                  |
| T8 | Reconsider Vercel for production, explore alternatives, implement on-demand updates| -        | todo   | -          | M3        | deployment, hosting, vercel, production  |
| T9 | Evaluate and potentially implement KeyCDN                                          | -        | todo   | -          | M3        | cdn, performance, infrastructure         |
| T10| Plan to purchase ip-api plan when user base grows                                  | -        | todo   | -          | M3        | api, geolocation, cost, scaling          |
| T11| Regenerate all API keys in `.env` after Vault secret management is implemented     | -        | todo   | M6         | M3        | security, secrets, vault, deployment     |
| T12| Define/implement standard for Svelte header UI structure docs for auto-doc gen     | -        | todo   | -          | M4        | frontend, documentation, svelte, ui      |
| T13| Investigate/implement native video capture in web app camera view on iOS           | -        | todo   | -          | M4        | frontend, mobile, ios, camera, video     |
| T14| Implement core offline mode features: offline search, view history, save drafts    | -        | todo   | -          | M4        | frontend, offline, pwa, search, chat     |
| T15| Implement double-tap gesture on touch devices for chat switching/menu              | -        | todo   | -          | M4        | frontend, mobile, ux, gestures           |
| T16| Implement PDF viewing using svelte-pdf                                             | -        | todo   | -          | M4        | frontend, pdf, svelte                    |
| T17| Integrate automated documentation generation (linked to UI structure YML/headers)  | -        | todo   | T12        | M4        | documentation, automation, frontend      |
| T18| Add offline unlock PIN feature                                                     | -        | todo   | T14        | M4        | frontend, offline, security, pwa         |
| T19| Implement server settings management (updates, invite codes)                       | -        | todo   | -          | M4        | backend, admin, settings                 |
| T20| Implement logic for Mate to suggest starting new chat if conversation too long     | -        | todo   | -          | M4        | backend, chat, ux, llm                   |
| T21| Implement custom 404 page with auto-search functionality                           | -        | todo   | -          | M4        | frontend, ux, search, error-handling     |
| T22| Load necessary text content into IndexedDB for offline search/404 page             | -        | todo   | T14, T21   | M4        | frontend, offline, pwa, search           |
| T23| Add language selection button                                                      | -        | todo   | -          | M4        | frontend, ui, i18n                       |
| T24| Implement chat collections feature                                                 | -        | todo   | -          | M4        | frontend, backend, chat, ux              |
| T25| Implement auto-suggestion to add new chats to collections                          | -        | todo   | T24        | M4        | frontend, backend, chat, ux, ai          |
| T26| Implement SEO improvements for website discoverability                             | -        | todo   | -          | M5        | seo, website, marketing                  |
| T27| Create centralized YML file for all translations                                   | -        | todo   | -          | M5        | i18n, backend, frontend, content         |
| T28| Develop script to generate language JSON files from translation YML                | -        | todo   | T27        | M5        | i18n, automation, script, build          |
| T29| Create YML files for Privacy Policy and Terms of Use content                       | -        | todo   | -          | M5        | legal, content, documentation, compliance|
| T30| Implement LLM-based generation of Privacy Policy & ToU from YML files              | -        | todo   | T29        | M5        | legal, automation, llm, compliance       |
| T31| Implement system for blog posts managed via YML files                              | -        | todo   | -          | M5        | content, blog, cms, website              |
| T32| Add automated translation for blog posts on commit                                 | -        | todo   | T27, T31   | M5        | i18n, automation, blog, ci               |
| T33| Create separate Privacy Policies for web app and API                               | -        | todo   | T29        | M5        | legal, documentation, privacy, compliance|
| T34| Set up admin email notifications for user credit purchases                         | -        | todo   | -          | M6        | notifications, admin, billing, email     |
| T35| Implement admin notifications for gift card application (with revoke option)       | -        | todo   | -          | M6        | notifications, admin, billing, security  |
| T36| Verify and document implementation of user data and chat backups                   | -        | todo   | -          | M6        | backup, compliance, documentation, data  |
| T37| Develop script for automated server security testing                               | -        | todo   | -          | M6        | security, testing, automation, devops    |
| T38| Add watermarking to OpenMates source code                                          | -        | todo   | -          | M6        | security, legal, licensing, code         |
| T39| Update compliance logging for Terms & Privacy consent events                       | -        | todo   | -          | M6        | compliance, logging, legal, privacy      |
| T40| Perform thorough cleaning of Git history for secrets/sensitive data                | -        | todo   | -          | M6        | security, git, devops, open-source       |
| T41| Add confirmation prompt before logging out user                                    | -        | todo   | -          | M6        | frontend, ux, security                   |
| T42| Implement secure email address change process                                      | -        | todo   | -          | M6        | security, auth, backend, email           |
| T43| Implement secure 2FA app reset process                                             | -        | todo   | -          | M6        | security, auth, backend, 2fa             |
| T44| Implement generation/confirmation of new backup codes                              | -        | todo   | -          | M6        | security, auth, backend, 2fa             |
| T45| Hardcode embedded safety system prompt for message pre-checking                    | -        | todo   | -          | M6        | security, ai, llm, safety, backend       |
| T46| Enhance Grafana dashboards and logging infrastructure                              | -        | todo   | -          | M7        | monitoring, logging, grafana, devops     |
| T47| Implement automated frontend tests (e.g., Playwright)                              | -        | todo   | -          | M7        | testing, frontend, automation, ci        |
| T48| Create script for periodic email delivery monitoring                               | -        | todo   | -          | M7        | monitoring, email, reliability, script   |
| T49| Implement PDF text extraction using Mistral OCR (or alternative)                   | -        | todo   | -          | M8        | ai, pdf, ocr, backend, feature           |
| T50| Integrate Sightengine (or alternative) for AI image moderation                     | -        | todo   | -          | M8        | ai, moderation, images, safety, api      |
| T51| Implement comprehensive safety processing pipeline                                 | -        | todo   | -          | M8        | ai, safety, llm, backend, security       |
| T52| Research/implement strategy for auto-switching AI models                           | -        | todo   | -          | M8        | ai, llm, backend, performance, cost      |
| T53| Investigate/integrate new video AI models (Hedra, Moon Valley)                     | -        | todo   | -          | M8        | ai, video, llm, research, feature        |
| T54| Implement clear labeling for AI model use cases                                    | -        | todo   | -          | M8        | ai, ux, frontend, documentation          |
| T55| Implement clear labeling for AI model copyright clarity                            | -        | todo   | -          | M8        | ai, ux, legal, copyright, documentation  |
| T56| Implement calendar integration workflow (holiday info)                             | -        | todo   | -          | M9        | feature, integration, calendar, backend  |
| T57| Evaluate making offline data storage opt-in                                        | -        | todo   | T14        | M9        | privacy, security, offline, ux, feature  |


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

### T8 - Reconsider Vercel for production, explore alternatives, implement on-demand production updates
Evaluate the suitability of Vercel for hosting the production frontend. Research alternative hosting providers if necessary. Implement a deployment strategy that allows for manual, on-demand triggering of production updates rather than automatic deployment on every commit.

### T9 - Evaluate and potentially implement KeyCDN
Research KeyCDN or other Content Delivery Networks (CDNs) to assess potential benefits for performance and scalability. Implement if deemed beneficial.

### T10 - Plan to purchase ip-api plan when user base grows
Monitor user growth and plan to subscribe to a paid ip-api.com plan when usage necessitates it for IP geolocation features.

### T11 - Regenerate all API keys in `.env` after Vault secret management is implemented
Once HashiCorp Vault is fully integrated for secrets management, systematically regenerate all API keys currently stored (even temporarily) in `.env` files or other insecure locations and store them securely in Vault.

### T12 - Define/implement standard for Svelte header UI structure docs for auto-doc gen
Establish a clear, concise format for documenting UI structure (visible elements, purpose, interactions) within comments at the header of Svelte component files. Implement this standard in key components to facilitate future automated documentation generation.

### T13 - Investigate/implement native video capture in web app camera view on iOS
Research methods to enable video recording using the native camera interface within a web application on iOS devices, overcoming limitations where only photo mode might be accessible by default. Implement a working solution.

### T14 - Implement core offline mode features: offline search, view history, save drafts
Develop the necessary frontend logic and local storage mechanisms (e.g., IndexedDB) to allow users to perform full-text search within their chats, view all past messages, and compose new messages (saved as editable drafts) while offline. Drafts should be sent automatically when connectivity is restored.

### T15 - Implement double-tap gesture on touch devices for chat switching/menu
Add touch event listeners to detect double-taps on the left or right side of the screen on mobile/touch devices. Implement logic to switch to the previous/next chat or open a context menu, ensuring it doesn't conflict with standard browser swipe gestures (like Safari's back/forward).

### T16 - Implement PDF viewing using svelte-pdf
Integrate the `svelte-pdf` library or a similar solution to allow users to view PDF documents directly within the web application interface.

### T17 - Integrate automated documentation generation (linked to UI structure YML/headers)
Develop or integrate a tool that can parse the standardized UI structure documentation (from T12, potentially YML or Svelte headers) and automatically generate user-facing or technical documentation, ensuring it stays up-to-date with code changes.

### T18 - Add offline unlock PIN feature
Implement a feature allowing users to set a PIN code to unlock the application when accessed offline, adding a layer of security for locally stored data.

### T19 - Implement server settings management (updates, invite codes)
Develop backend APIs and potentially an admin interface section for managing server-level settings, such as triggering software updates or generating/managing user invitation codes.

### T20 - Implement logic for Mate to suggest starting new chat if conversation too long
Add logic (potentially in the backend or triggered by frontend) to detect when a chat conversation exceeds a certain length or context limit and have the Mate proactively suggest starting a new chat topic to maintain focus and performance.

### T21 - Implement custom 404 page with auto-search functionality
Create a user-friendly custom 404 "Not Found" page. Integrate a search bar on this page that automatically initiates a search based on the path segments of the URL that led to the 404 error.

### T22 - Load necessary text content into IndexedDB for offline search/404 page
Identify essential text content (e.g., UI labels, help text, potentially searchable content indices) and implement logic to proactively load and store this data in the browser's IndexedDB upon application load or update, making it available for offline features like search (T14) and the 404 page (T21).

### T23 - Add language selection button
Implement a UI element (e.g., a dropdown or button in the header/settings) allowing users to select their preferred language for the application interface. Connect this to the internationalization (i18n) system.

### T24 - Implement chat collections feature
Develop the backend models and APIs, along with frontend UI components, to allow users to group related chats into named collections for better organization.

### T25 - Implement auto-suggestion to add new chats to collections
After a new chat is created and the first few messages are exchanged, implement logic (potentially AI-driven) to analyze the topic and suggest relevant existing collections the user might want to add the chat to.

### T26 - Implement SEO improvements for website discoverability
Review and implement Search Engine Optimization (SEO) best practices for the public-facing website to improve its ranking and visibility in search engine results (e.g., Google). This includes optimizing titles, descriptions, keywords, site structure, and potentially generating a sitemap.

### T27 - Create centralized YML file for all translations
Establish a single YAML file (`translations.yml` or similar) as the source of truth for all UI text strings and their translations across supported languages. Define a clear structure for this file.

### T28 - Develop script to generate language JSON files from translation YML
Create an automated script (e.g., Python, Node.js) that reads the central `translations.yml` file and generates separate JSON files for each language (e.g., `en.json`, `de.json`), suitable for consumption by frontend i18n libraries. Ensure the script handles nested structures and potential variables within translations.

### T29 - Create YML files for Privacy Policy and Terms of Use content
Structure the content for the Privacy Policy and Terms of Use documents into separate YAML files. Break down the content into logical sections suitable for potential automated generation or processing.

### T30 - Implement LLM-based generation of Privacy Policy & ToU from YML files
Explore and potentially implement a process using a Large Language Model (LLM) to take the structured content from the Privacy Policy and Terms of Use YML files (T29) and generate well-formatted, human-readable documents in Markdown or HTML.

### T31 - Implement system for blog posts managed via YML files
Design and implement a system where blog post content is written and managed using individual YAML files. Define the structure for these files (e.g., title, author, date, content sections). Develop backend/frontend logic to read these files and render them as blog posts on the website.

### T32 - Add automated translation for blog posts on commit
Integrate an automated translation service (e.g., using an LLM API or a dedicated translation API) into the CI/CD pipeline. Configure it to trigger whenever a blog post YML file (T31) is committed, automatically generating translated versions based on the central translation file (T27) or service.

### T33 - Create separate Privacy Policies for web app and API
Draft distinct Privacy Policy documents tailored specifically to the data processing activities of the main web application and the public developer API, respectively. Ensure they align with the overall design and structure of the documentation pages.

### T34 - Set up admin email notifications for user credit purchases
Implement backend logic to detect when a user successfully completes a credit purchase transaction via the payment provider (e.g., Revolut). Trigger an email notification to a designated administrator address containing relevant details of the purchase.

### T35 - Implement admin notifications for gift card application (with revoke option)
Implement backend logic to send an email notification to administrators whenever a gift card code is successfully applied to a user's account. Include details like the user, the gift card code, and the amount. Add a secure mechanism (e.g., a link in the email leading to an admin action) allowing admins to revoke the applied credits if the transaction seems fraudulent or suspicious.

### T36 - Verify and document implementation of user data and chat backups
Review the current backup procedures for user account data (e.g., from Directus/Postgres) and encrypted chat data. Ensure backups are running correctly, stored securely, and test the restoration process. Document the entire backup and restore strategy clearly.

### T37 - Develop script for automated server security testing
Create a script (e.g., using Python with security libraries, or integrating existing tools) that performs automated checks for common server vulnerabilities, misconfigurations, open ports, and adherence to security best practices outlined in the guidelines. Integrate this into CI/CD or run periodically.

### T38 - Add watermarking to OpenMates source code
Investigate methods for adding subtle watermarks or identifiers within the source code itself. Implement a chosen method, considering the implications for readability, performance, and the planned open-source release.

### T39 - Update compliance logging for Terms & Privacy consent events
Ensure that events related to users accepting specific versions of the Terms of Service and Privacy Policy are logged for compliance purposes. The log entry should include user ID, timestamp, the specific version number of the document agreed to, and ideally a link or reference to the exact text of that version.

### T40 - Perform thorough cleaning of Git history for secrets/sensitive data
Before making the repository public (open source), use tools like `git-filter-repo` or BFG Repo-Cleaner to meticulously scan and remove any accidentally committed secrets (API keys, passwords), sensitive configuration files, or personal identifiable information (PII) from the entire Git history.

### T41 - Add confirmation prompt before logging out user
Modify the logout functionality in the frontend to display a confirmation dialog box asking the user if they are sure they want to log out before proceeding with the action.

### T42 - Implement secure email address change process
Develop the multi-step process for changing a user's email address securely: require 2FA OTP, send notification to old email, send verification code to new email, implement a 48-hour delay with reminder notifications to the old address, and send final confirmation to both addresses upon completion.

### T43 - Implement secure 2FA app reset process
Develop the process for resetting a user's 2FA application: user initiates reset in settings, receives a one-time code via email with security warnings, confirms code in the app, system generates a new 2FA secret, user adds new secret to their authenticator app, old secret is invalidated.

### T44 - Implement generation/confirmation of new backup codes
Add functionality for users to generate a new set of 2FA backup codes if they have used all their existing ones. Ensure the process requires confirmation (e.g., entering current password or 2FA OTP) before generating and displaying new codes.

### T45 - Hardcode embedded safety system prompt for message pre-checking
Define a robust system prompt focused on safety and ethical guidelines. Embed this prompt directly within the backend code that handles message pre-processing before sending user input to the LLM. This makes it harder for self-hosted instances to bypass safety checks simply by changing configuration.

### T46 - Enhance Grafana dashboards and logging infrastructure
Review and improve Grafana dashboards for better monitoring. Implement automated deletion of old logs from Loki based on retention policies. Set up automated, encrypted backups of compliance logs to S3. Add tracking for invite code usage, website traffic, active users, income, credit usage, and API response times.

### T47 - Implement automated frontend tests (e.g., Playwright)
Set up Playwright or a similar end-to-end testing framework. Write automated tests covering critical user flows in the frontend web application, such as signup, login, chat interaction, and key settings changes. Integrate these tests into the CI/CD pipeline.

### T48 - Create script for periodic email delivery monitoring
Develop a script that runs on a schedule (e.g., every 30 minutes via cron or Celery Beat). The script should send a test email via the standard email sending service (e.g., Mailjet) to a monitored inbox and potentially measure the time taken for delivery, logging results or alerting on failures/delays.

### T49 - Implement PDF text extraction using Mistral OCR (or alternative)
Integrate an OCR service (like Mistral's API or another provider/library) to extract text content from PDF files uploaded or processed by users, enabling features like searching within PDFs or using their content as input for AI models.

### T50 - Integrate Sightengine (or alternative) for AI image moderation
Integrate the Sightengine API or a similar service to automatically scan images uploaded by users for potentially unsafe or inappropriate content (e.g., violence, adult content, hate symbols). Implement actions based on the moderation results (e.g., blocking the image, flagging for review).

### T51 - Implement comprehensive safety processing pipeline
Develop a multi-stage pipeline for processing user messages and AI responses to enhance safety: detect spam/harmful content/scams/propaganda, preprocess messages, calculate a suspicion score, potentially steer conversations or educate users, track suspicious behavior across accounts/devices, and perform post-generation safety checks on AI responses triggered by suspicious inputs.

### T52 - Research/implement strategy for auto-switching AI models
Investigate and develop a strategy for dynamically selecting the most appropriate AI model (e.g., different providers like OpenAI, Anthropic, Google Gemini, or different model sizes) based on the context of the user's request (e.g., length of input, task type like summarization vs. creative writing, processing requirements like video analysis). Implement the routing logic in the backend.

### T53 - Investigate/integrate new video AI models (Hedra, Moon Valley)
Research emerging text-to-video or image-to-video AI models like Hedra or Moon Valley. Evaluate their capabilities, API availability, pricing, and terms. If suitable, plan and implement integration to offer video generation features.

### T54 - Implement clear labeling for AI model use cases
In the UI where users might interact with different AI models (especially for image/video generation), provide clear labels or descriptions indicating what each model is best suited for (e.g., "Realistic Photos," "Character Animation," "Product Shots").

### T55 - Implement clear labeling for AI model copyright clarity
Research and provide clear information to users about the copyright implications or terms of use associated with the output generated by different AI models offered, especially regarding commercial use or ownership of generated content.

### T56 - Implement calendar integration workflow (holiday info)
Explore integrating with calendar APIs or services. Implement a simple workflow where the Mate can access calendar information (initially, perhaps just public holidays for the user's region) and inform the user about upcoming holidays.

### T57 - Evaluate making offline data storage opt-in
Consider the privacy and security implications of storing chat data offline by default (T14). Evaluate changing this to an opt-in feature, where users must explicitly enable offline storage in settings, potentially with clearer warnings about local data security.