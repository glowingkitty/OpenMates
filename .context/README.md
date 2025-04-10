# Purpose

The .context folder includes files that describe important context about the project. Relevant for both humans and AI to better understand the project and to make sure all guidelines are followed when making changes to the project. You can add your own .md files to better structure the context of your project better. But keep in mind that you want to be concise, since both humans and AI could make increasingly mistakes, if the project context is getting very long and it also increases costs and response time from AI models. Also keep in mind that not all recommended chapters are required for every project and you may choose to add custom chapters.

IMPORTANT: Remember to always keep the Markdown files in /.context up to date!

# Recommended default files:
- todo.md
- project-overview.md
- architecture-guidelines.md
- coding-guidelines.md
- design-guidelines.md
- compliance-guidelines.md
- security-guidelines.md
- privacy-guidelines.md

# Rules for files inside .context folder

Always make sure to follow these rules when writing / updating the files inside the .context folder.

## Markdown files

### Structure
1. heading: similar to filename (example: coding-guidelines.md -> Coding Guidelines)
2. table of content
3. chapters with text


## File specific rules

### todo.md

#### Structure
Required notes:
'When you start working on a task, always change the status from todo to 'in-progress'.
Required chapters:
1. **Milestones**
   1. table has these fields:
      1. ID (M1, M2, etc.)
      2. Title (required)
      3. Target Date (YYYY-MM-DD)
      4. Tasks (T1, T2, etc.)
      5. Status (todo, in-progress, done)
2. **Milestone Descriptions**
   1. content:
      1. headline: {ID} - {Title}
      2. text: {description}
3. **Tasks**
   1. table has these fields:
      1. ID (T1, T2, etc.)
      2. Title
      3. Priority (-, Low, Medium, High)
      4. Status (todo, in-progress, done)
      5. Depends on (- or T1, T2, etc.)
      6. Milestone (-, or M1, M2, etc.)
      7. Tags
4. **Task Descriptions**
   1. content:
      1. headline: {ID} - {Title}
      2. text: {description}

### project-overview.md

#### Structure
Recommended chapters:
1. **Project overview**
    *   Project name and short description
2. **Target groups**
    *   Target groups & communication style
3. **Highlights**
    *   Bulletpoints of what makes this project unique and different from others

### architecture-guidelines.md

#### Structure
- use embedded mermaid charts + concise bulletpoint based descriptions

### coding-guidelines.md

#### Structure
Recommended chapters:
1.  **General Principles**
    *   Core philosophies (e.g., Readability, Simplicity (KISS), Don't Repeat Yourself (DRY), Consistency).
    *   Code ownership and responsibility.
2.  **Code Formatting & Style**
    *   Reference to specific style guides per language (e.g., PEP 8 for Python, Airbnb/StandardJS for JS/TS).
    *   Mandatory automated tooling (Linters, Formatters like Prettier, Black, Ruff, ESLint) and how to use them.
    *   Naming Conventions (variables, functions, classes, modules, files, etc.).
    *   Indentation, spacing, line length limits.
3.  **Code Structure & Organization**
    *   Project/repository structure guidelines.
    *   Module/Component design (e.g., Single Responsibility Principle, SOLID where applicable).
    *   Directory structure conventions (e.g., separating interfaces, implementations, tests).
4.  **Comments & Documentation**
    *   When to write comments (explaining the *why*, not the *what*).
    *   Code comment style and format.
    *   Documentation standards (e.g., Docstrings for functions/classes, README standards).
5.  **Error Handling & Logging**
    *   Preferred error handling strategies (e.g., exceptions vs. error codes).
    *   Logging levels and practices (what to log, format).
    *   Handling expected vs. unexpected errors.
6.  **Testing**
    *   Importance and philosophy of testing.
    *   Types of tests required (Unit, Integration, End-to-End) and their scope.
    *   Test coverage expectations.
    *   Preferred testing frameworks and libraries.
    *   Test naming and organization conventions.
7.  **Version Control (Git)**
    *   Branching strategy (e.g., Gitflow, GitHub Flow, Trunk-Based).
    *   Commit message format (e.g., Conventional Commits).
    *   Pull Request (PR) process (requirements, review expectations, merging).
    *   Handling merge conflicts.
8.  **Security Best Practices**
    *   Input validation and sanitization.
    *   Secrets management (avoiding hardcoded secrets).
    *   Dependency management and vulnerability scanning.
    *   Authentication and authorization patterns.
    *   Awareness of common vulnerabilities (e.g., OWASP Top 10).
9.  **Performance Considerations**
    *   Guidelines on writing efficient code (avoiding premature optimization).
    *   Identifying and addressing performance bottlenecks.
    *   Use of caching where appropriate.
10. **Language/Framework Specific Guidelines** (Can be subsections or links to separate documents)
    *   *Examples:* Specific rules, patterns, or anti-patterns for technologies used in the project (e.g., Python/FastAPI, TypeScript/Svelte).
    *   Specific rules for other relevant technologies (e.g., Dockerfiles, CI/CD pipelines).
11. **Tooling & Environment**
    *   Required development tools and versions.
    *   Environment setup instructions or references.
    *   IDE configuration recommendations (e.g., editorconfig, recommended extensions).

### design-guidelines.md

#### Structure
Recommended chapters:
1.  **Core Design Principles:** Overview of the fundamental design philosophy.
2.  **Branding & Visual Identity:** Guidelines for logo, color palette, and typography.
3.  **Layout & Spacing:** Rules for structuring pages and elements.
4.  **UI Components & Patterns:** Description and usage of standard UI elements (buttons, forms, etc.).
5.  **Iconography & Imagery:** Standards for using icons and images.
6.  **Accessibility (a11y):** Requirements for ensuring usability for all users.
7.  **Tone of Voice:** Guidelines for language and style in UI text.

### security-guidelines.md

#### Structure
Recommended chapters:
1.  **Threat Modeling & Attack Vectors**
    *   Authentication & Session Management (e.g., Brute force, session hijacking)
    *   Authorization & Access Control (e.g., Privilege escalation)
    *   Input Validation & Injection (e.g., SQLi, XSS)
    *   API Security (e.g., Rate limiting abuse)
    *   Denial of Service (DoS/DDoS)
    *   Data Security (e.g., Sensitive data exposure)
    *   Third-Party Dependencies
2.  **Security Measures & Countermeasures**
    *   Authentication (e.g., Hashing, MFA)
    *   Session Management (e.g., Secure cookies, timeouts)
    *   Authorization (e.g., RBAC)
    *   Input Sanitization & Validation
    *   API Security (e.g., Rate limiting, API keys)
    *   Infrastructure Security (e.g., Firewalls, WAF)
    *   Data Encryption (At rest, in transit)
    *   Secrets Management (e.g., Vault)
    *   Dependency Management (e.g., Scanning)
3.  **Security Testing & Monitoring**
    *   Static Analysis (SAST)
    *   Dynamic Analysis (DAST)
    *   Penetration Testing
    *   Security Monitoring & Alerting (e.g., Logging, SIEM/alerting tools)
4.  **Incident Response Plan** (Outline)

### compliance-guidelines.md

#### Structure
Recommended chapters:
1.  **Regulatory Landscape**
    *   GDPR (Data Subject Rights, Lawful Basis, DPIAs, Breach Notifications)
    *   Other relevant regulations (e.g., CCPA, HIPAA)
2.  **Compliance Logging Requirements**
    *   Purpose of logging
    *   Events Logged (Authentication, Authorization, Data Access/Modification, Admin Actions, Key API Calls)
    *   Log Format & Content (Timestamp, User ID, IP, Action, Outcome, etc.)
    *   Log Storage & Retention (Location, period, access controls)
    *   Log Monitoring & Review Procedures
3.  **Data Handling Procedures**
    *   Data Inventory & Mapping
    *   Data Retention & Deletion Policies
    *   Third-Party Data Sharing Policies
4.  **Compliance Audits & Certifications** (Internal/external audits)

### privacy-guidelines.md

#### Structure
Recommended chapters:
1.  **Introduction:**
    *   Project's commitment to privacy.
2.  **Guiding Privacy Principles:**
    *   High-level standards (e.g., data minimization, privacy by design).
3.  **Data Collection Policy:**
    *   What data IS collected (and why), what data IS NOT collected.
4.  **Sensitive Data Handling:**
    *   Procedures for processing, storing, protecting sensitive data.
5.  **Third-Party Providers & Data Sharing:**
    *   List of services (hosting, email, etc.) and data shared.
6.  **User Rights & Control:**
    *   How users can exercise their rights (access, deletion).
7.  **End-User Contact Methods:**
    *   Describe the intended methods for end-users to contact the project team regarding privacy (e.g., "Specify that a contact form should be available", "Define a standard privacy email like privacy@projectdomain.com").