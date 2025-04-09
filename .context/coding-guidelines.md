# Coding Guidelines

## Table of Contents

- [Coding Guidelines](#coding-guidelines)
  - [Table of Contents](#table-of-contents)
  - [1. General Principles](#1-general-principles)
  - [2. Code Formatting \& Style](#2-code-formatting--style)
  - [3. Code Structure \& Organization](#3-code-structure--organization)
  - [4. Comments \& Documentation](#4-comments--documentation)
  - [5. Error Handling \& Logging](#5-error-handling--logging)
  - [6. Testing](#6-testing)
  - [7. Version Control (Git)](#7-version-control-git)
  - [8. Security Best Practices](#8-security-best-practices)
  - [9. Performance Considerations](#9-performance-considerations)
  - [10. Language/Framework Specific Guidelines](#10-languageframework-specific-guidelines)
  - [11. Tooling \& Environment](#11-tooling--environment)

## 1. General Principles

*   **Readability:** Code should be clear, understandable, and easy to follow. Prioritize clarity over cleverness.
*   **Simplicity (KISS):** Write the simplest code that fulfills the requirements. Avoid unnecessary complexity.
*   **Don't Repeat Yourself (DRY):** Avoid duplicating code logic. Actively look for opportunities to refactor common functionality into reusable functions, classes, or components, rather than redefining similar logic in multiple places.
*   **Consistency:** Adhere to these guidelines to ensure consistency across the codebase, making it easier to navigate and maintain.
*   **Code Ownership:** While individuals may work on features, the codebase is collectively owned. Strive to improve any code you touch.

## 2. Code Formatting & Style

*   **Automated Tooling (Mandatory):** All code MUST be formatted and linted using the project's standard tools before committing. Configure your editor to use these tools.
    *   **Python:**
        *   Formatter: **Black** (default configuration).
        *   Linter: **Ruff** (use project's `pyproject.toml` or `.ruff.toml` configuration).
        *   Style Guide: Follow **PEP 8**.
    *   **TypeScript/JavaScript/Svelte:**
        *   Formatter: **Prettier** (use project's `.prettierrc` configuration).
        *   Linter: **ESLint** with Svelte support (use project's `.eslintrc.js` or similar configuration, likely based on Airbnb or Svelte recommended rules).
*   **Naming Conventions:**
    *   Use clear, descriptive names for variables, functions, classes, etc.
    *   Python: `snake_case` for variables and functions, `PascalCase` for classes. Follow PEP 8 naming conventions.
    *   TypeScript/Svelte: `camelCase` for variables and functions, `PascalCase` for classes and components.
    *   Files: Use `kebab-case` or `snake_case` consistently based on language conventions (e.g., `user_service.py`, `UserProfile.svelte`, `api-client.ts`).
*   **Indentation:** Use 4 spaces for Python. Use 2 or 4 spaces for TS/JS/Svelte as defined by Prettier configuration.
*   **Line Length:** Adhere to limits set by formatters (e.g., Black's default, Prettier's default).

## 3. Code Structure & Organization

*   **Monorepo Structure:** Maintain the top-level separation between `backend`, `frontend`, `shared`, `e2e_tests`, etc.
*   **Backend:**
    *   Core services, API logic, shared utilities in `/backend/core`.
    *   Application-specific Dockerfiles, setup scripts, or distinct services in `/backend/apps/*`.
    *   Organize API code using FastAPI routers/apps.
*   **Frontend:**
    *   Reusable UI components and logic in `/frontend/packages`.
    *   Specific web applications in `/frontend/apps`.
    *   Structure Svelte apps logically (e.g., by feature or component type).
*   **Module/Component Design:**
    *   Follow the Single Responsibility Principle (SRP): Modules/classes/functions/components should ideally do one thing well.
    *   Keep components and functions small and focused. Aim to keep files under approximately 400 lines of code; larger files should be considered for refactoring into smaller, more manageable modules.
*   **Test File Location:**
    *   Unit/Integration/Component tests MUST be co-located with the source code they test.
        *   Python: `test_*.py` alongside `*.py`.
        *   TS/Svelte: `*.test.ts` or `*.spec.ts` alongside `*.ts` or `*.svelte`.
    *   End-to-End (E2E) tests (Playwright) reside in the top-level `/e2e_tests` directory.

## 4. Comments & Documentation

*   **When to Comment:** Comment the *why*, not the *what*. Explain complex logic, assumptions, or the reasoning behind a particular implementation if it's not obvious from the code itself.
*   **Docstrings (Mandatory):**
    *   All public functions, classes, and modules MUST have docstrings.
    *   **Python:** Use **Google style** docstrings. Include description, `Args:`, `Returns:`, and `Raises:`.
    *   **TypeScript/Svelte:** Use **JSDoc** comments (`/** ... */`). Include description, `@param`, `@returns`, `@throws`.
*   **Type Hinting (Mandatory):**
    *   Use Python type hints for all function signatures and variables where appropriate.
    *   Leverage TypeScript's static typing system fully.
*   **README Files:**
    *   Maintain a comprehensive top-level `/README.md`.
    *   Maintain READMEs for major sections (`/backend/README.md`, `/frontend/README.md`).
    *   Add READMEs for complex, reusable packages or apps (e.g., `/frontend/packages/ui/README.md`) as needed.
    *   READMEs should explain purpose, setup, usage, testing, and key decisions.

## 5. Error Handling & Logging

*   **Error Handling:**
    *   Use exceptions for exceptional circumstances in Python. Be specific with exception types.
    *   Handle errors gracefully in TypeScript/JavaScript (e.g., using try-catch, Promise rejections).
    *   Provide clear error messages for API responses and user interfaces.
    *   Validate external input rigorously (API requests, user input).
*   **Logging:**
    *   Use a structured logging library (e.g., Python's standard `logging` module configured appropriately).
    *   Log important events, errors, and key decision points.
    *   Avoid logging sensitive information (passwords, API keys, PII).
    *   Use appropriate log levels:
        *   **Development:** Default to `INFO` level. Send logs to Loki/Grafana for visibility.
        *   **Production:** Default to `WARNING` level to reduce noise. Send logs to Loki/Grafana.
        *   **DEBUG Level:** Use `DEBUG` logs in code for detailed diagnostic information useful during troubleshooting. These should be disabled by default in both dev and prod environments but enableable via configuration (e.g., environment variable) when needed.

## 6. Testing

*   **Philosophy:** Aim for a balanced test suite that provides confidence in code correctness and prevents regressions. Test critical paths thoroughly.
*   **Types & Tools:**
    *   **Backend Unit/Integration:** `pytest`.
    *   **Frontend Unit/Component:** `Vitest`.
    *   **End-to-End (E2E):** `Playwright`.
*   **Execution:**
    *   Unit/Component/Integration tests (pytest, Vitest) should run frequently (e.g., locally, on commit/push in CI).
    *   E2E tests (Playwright) should *ideally* run automatically on Pull Requests before merging to `main` (once a branching workflow is fully adopted). *Currently*, while working primarily on `main`, consider running E2E tests manually before significant changes or on a regular schedule (e.g., nightly) against a development/staging deployment.
*   **Email Testing (E2E):** Use a self-hosted **MailHog** instance during automated E2E test runs to intercept and verify emails generated by the application.
*   **Security Testing:** Incorporate automated security scanning tools (e.g., dependency vulnerability scanning like Snyk/Dependabot, secret scanning like gitleaks) into the CI/CD pipeline.
*   **Testing External/Costly APIs:** Avoid hitting real, costly external APIs (e.g., LLMs, paid transcription services) during regular automated test runs.
    *   **Primary Strategy:** Use mocking or stubbing techniques (e.g., Python's `unittest.mock`, `vi.mock`) to simulate the API's behavior within unit and integration tests.
    *   **Secondary Strategy (Use Sparingly):** If direct integration testing is absolutely necessary, use specific test environments/keys if provided by the service. Mark these tests appropriately (e.g., `@pytest.mark.expensive`) and exclude them from default CI runs. Execute them manually or on a less frequent schedule (e.g., nightly) when validation against the real service is required.

## 7. Version Control (Git)

*   **Branching Strategy:** Use **GitHub Flow**. (Note: While currently working solo primarily on `main`, adopting this strategy early provides a clean history, enables automation, builds good habits, and prepares the project for future AI and human collaboration.)
    1.  `main` branch is always stable and deployable.
    2.  Create feature branches from `main` (e.g., `feat/new-feature`, `fix/bug-fix`).
    3.  Commit work to the feature branch.
    4.  Open a Pull Request (PR) to merge the feature branch into `main`.
    5.  Require code review and passing CI checks on PRs.
    6.  Merge PR into `main` after approval.
*   **Commit Messages:** Use **Conventional Commits** format (`type(scope): description`).
    *   Examples: `feat(auth): add password reset endpoint`, `fix(ui): correct button alignment on mobile`, `docs(readme): update setup instructions`, `test(api): add tests for user service`, `refactor(core): simplify logging configuration`, `ci: configure playwright tests`.
*   **Pull Requests (PRs):**
    *   Write clear PR descriptions explaining the changes and their purpose.
    *   Ensure CI checks (linting, formatting, tests) pass.
    *   Require at least one approval (if collaborators exist) before merging.

## 8. Security Best Practices

*   **Input Validation:** Validate and sanitize all external input rigorously on the **backend**. Frontend validation can be added for better user experience, but **backend validation is mandatory for security** as frontend checks can always be bypassed.
*   **Secrets Management:** NEVER commit secrets (API keys, passwords, certificates) directly to the repository.
    *   **Recommended:** Use **HashiCorp Vault** for managing *all* application secrets. Applications should authenticate to Vault at runtime (e.g., during startup) to fetch necessary secrets and inject them securely (e.g., as environment variables for the running process).
    *   **Avoid `.env` in Repo:** Do not commit `.env` files containing secrets. Be cautious as tools might inadvertently read local `.env` files.
    *   **Local Overrides:** `.env` files should *only* be used for non-sensitive, local development overrides (e.g., local database connection strings) and MUST be included in `.gitignore`.
*   **Dependency Management:** Regularly update dependencies and use automated tools (e.g., Snyk, Dependabot) to scan for known vulnerabilities.
*   **Authentication & Authorization:** Implement robust authentication and authorization mechanisms, leveraging Directus for user credential management where applicable. Follow best practices for session management (e.g., secure tokens/cookies), API key handling, 2FA, and access control logic within the application.
*   **API Security:** Protect APIs against common threats (e.g., rate limiting, proper authentication/authorization).
*   **Least Privilege:** Grant services and processes only the permissions they absolutely need.
*   **OWASP Top 10:** Be aware of and mitigate common web application security risks.

## 9. Performance Considerations

*   **Write Efficient Code:** Be mindful of performance, especially in critical code paths, but avoid premature optimization. Profile code if performance issues arise.
*   **Caching:** Use caching strategically (e.g., for frequently accessed, rarely changing data) where appropriate.
*   **Asynchronous Operations:** Utilize asynchronous programming (e.g., Python's `asyncio`, Node.js) for I/O-bound tasks to improve responsiveness.

## 10. Language/Framework Specific Guidelines

*   **Python/FastAPI:**
    *   Leverage FastAPI's dependency injection system.
    *   Use Pydantic for data validation and serialization.
    *   Follow FastAPI best practices for structuring applications.
*   **TypeScript/Svelte:**
    *   Utilize TypeScript's static typing effectively.
    *   Follow Svelte best practices for component structure, reactivity, and state management.
    *   Use SvelteKit features appropriately if applicable (routing, endpoints, etc.).
*   **MJML:** Follow MJML best practices for creating responsive email templates.
*   **Docker:** Write efficient and secure Dockerfiles (e.g., use multi-stage builds, non-root users).

## 11. Tooling & Environment

*   **Required Tools:** Specify required versions of key tools (Python, Node.js, Docker, etc.) if necessary (e.g., in a `.tool-versions` file or project README).
*   **Environment Setup:** Provide clear instructions or scripts for setting up the development environment (e.g., `docker-compose up`, `pnpm install`).
*   **IDE Configuration:** Recommend editor extensions that support the project's linters and formatters (e.g., extensions for Black, Ruff, Prettier, ESLint). Consider including an `.editorconfig` file for basic editor settings.