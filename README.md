# OpenMates™

[![OpenMates header image](./docs/images/openmates_header.png)](https://openmates.org)

## What is OpenMates?

OpenMates™ aims to become an open source alternative to ChatGPT, Claude, Manus, etc. - focused on the best user experience, fulfilling your tasks using a wide range of apps, privacy & encryption by default and compatibility with a wide range of AI models - making it also independent of specific companies. Currently in an early alpha stage online. The perfect time for you to join in on the development with your feedback & contributions.


[Click to show project overview slides PDF](./docs/slides/openmates_overview_slides.pdf)

> *The following documentation (as well as the code) are still in an early alpha stage. Keep in mind the current release of OpenMates is for developers and early testers only and many features are still missing.*

### Goal

![Goal header image](./docs/slides/openmates_pitch_slides/goal.jpg)

OpenMates aims to be the most user-friendly, privacy-focused and provider-independent AI agent software. With the goal to be the super app for most daily tasks for average users - combining the ease of use of chat based interactions with optimized user interfaces for various media & tasks.

#### Apps

![Apps header image](./docs/slides/openmates_pitch_slides/apps.jpg)

Apps are one of the core components of OpenMates. They allow your digital team mates to use various external providers to fullfill your requests - from searching the web, finding meetups, finding restaurants, generating images, transcribing videos, and much more.

[Click here to learn more](./docs/architecture/apps/README.md)

### Completed

![Completed header image](./docs/slides/openmates_pitch_slides/completed.jpg)

An early [alpha release of OpenMates without Apps](https://app.openmates.org) is available. And while there is still a lot of work to do, some core features are implemented and ready to allow enthusiastic early testers to test the web app and provide feedback. And a more stable and feature rich release is planned to be ready within 2025.

### What's next

![What's next header image](./docs/slides/openmates_pitch_slides/whats_next.jpg)

As you can see based on the [docs](./docs/architecture/README.md) and [issues](https://github.com/glowingkitty/OpenMates/issues) pages, there is a lot of work to do. But these are the next core features that will be implemented next:

- e2e - Only your devices can encrypt & decrypt your data (work in progress)
    - [docs/architecture/security.md](./docs/architecture/security.md)
- unified UI to show media & app skill use details (work in progress)
    - [docs/architecture/message_parsing.md](./docs/architecture/message_parsing.md)
    - [docs/architecture/message_input_field.md](./docs/architecture/message_input_field.md)
- Apps - the core of useful AI agents
    - [docs/architecture/apps/README.md](./docs/architecture/apps/README.md)
    - [docs/architecture/apps/app_skills.md](./docs/architecture/apps/app_skills.md)
    - [docs/architecture/apps/app_settings_and_memories.md](./docs/architecture/apps/app_settings_and_memories.md)
    - [docs/architecture/apps/videos.md](./docs/architecture/apps/videos.md)
    - [docs/architecture/apps/web.md](./docs/architecture/apps/web.md)
- follow up questions - to encourage learning
    - [docs/architecture/message_processing.md](./docs/architecture/message_processing.md#post-processing)
    - [docs/architecture/message_input_field.md](./docs/architecture/message_input_field.md)
- new website, with documentation
- auto select the best AI model for the task
    - [docs/architecture/message_processing.md](./docs/architecture/message_processing.md#pre-processing)
    - [docs/architecture/ai_model_selection.md](./docs/architecture/ai_model_selection.md)


### How to contribute

![How to contribute header image](./docs/slides/openmates_pitch_slides/contribute.jpg)

You can help by testing the web app and providing feedback. You can also help by contributing to the code.

[Click here to learn how to contribute](./docs/contributing.md)

## Cloud web app

[![Cloud web app header image](./docs/images/cloudwebapp_header.png)](https://app.openmates.org)

Want to test OpenMates without having to manage the deployment yourself? And also support the development financially at the same time? Then join our Discord group, where invite codes to sign up for OpenMates will be posted on a regular basis.

[Open web app](https://app.openmates.org)

## License

[![License header image](./docs/images/license_header.png)](https://www.gnu.org/licenses/why-affero-gpl.html)

OpenMates is licensed under AGPL.

### What is allowed?

- Run OpenMates on your local machine or private server
- Share access with your team or organization
- Create new open source software based on OpenMates (commercial use allowed)
- Use OpenMates alongside other software on the same server

### What is prohibited?

- Offering OpenMates as a service to outside users while keeping your code changes private
- Creating software based on OpenMates under a different license than AGPL
- Combining OpenMates code with proprietary code in the same application

### Key requirement:

If you provide OpenMates as a network service to others (like a public website or API), you must make your complete source code - including any modifications - available to the public.

[Open GNU website with more details](https://www.gnu.org/licenses/why-affero-gpl.html)

## Self-hosted setup

![Self hosted setup header image](./docs/images/selfhostedsetup_header.png)

### Setup

1.  **Clone the repository**
    ```bash
    git clone https://github.com/glowingkitty/OpenMates
    cd OpenMates
    ```
2.  **Run the setup script**
    This will check for dependencies (Docker, Docker Compose, pnpm) and install them if missing. It will also create your `.env` file, generate necessary secrets, and set up the Docker network.
    ```bash
    chmod +x setup.sh
    ./setup.sh
    ```
    *Note: The script requires `sudo` to install missing dependencies. It is designed for Debian-based systems (like Ubuntu). If you're on another OS, please install the dependencies manually.*

3.  **Add your API keys**
    Open the newly created `.env` file and add your secret API keys for any services you want to use (e.g., Mailjet, Google, etc.).

### Start the services

Once the initial setup is complete, you can start the services. For a typical development setup, you'll run the backend services using Docker and the frontend service directly using pnpm for a better development experience (e.g., hot-reloading).

-   **1. Start the backend services:**
    This command starts all the necessary background services (like the API, database, etc.).
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml up -d
    ```
    *Note: To also access the web UIs for services like Directus (CMS) and Grafana (Monitoring), you need to include the override file. Use the following command instead:*
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
    ```
    - Directus will be available at [http://localhost:8055](http://localhost:8055)
    - Grafana will be available at [http://localhost:3000](http://localhost:3000)

-   **2. Check Vault for secret import:**
    After starting the services, check the logs of the `vault-setup` container to ensure all your secrets from the `.env` file have been successfully imported into Vault.
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml logs vault-setup
    ```
    If the logs indicate a successful import, you should update your `.env` file by replacing the actual API key values with `IMPORTED_TO_VAULT`. This prevents the keys from being re-imported on subsequent startups and keeps them from being exposed in the `.env` file.

    For example, if your `.env` file has:
    `SECRET__MISTRAL_AI__API_KEY=your_secret_key`

    You should change it to:
    `SECRET__MISTRAL_AI__API_KEY=IMPORTED_TO_VAULT`

-   **3. Start the frontend service (for development):**
    This command starts the web app with hot-reloading, which is ideal for development.
    ```bash
    pnpm --filter web_app dev --host 0.0.0.0 --port 5174
    ```
    *Note: The first time you access the web app, it may take up to a minute to load as Svelte builds the necessary files.*

-   **4. Check for your invite code:**
    The initial setup generates an invite code for the first user. Check the logs of the `cms-setup` container to find it.
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml logs cms-setup
    ```
-   **5. Access the web app:**
    Open [http://localhost:5174](http://localhost:5174) in your browser. Click "Sign Up" and use the invite code to create your account.

### Manage the services

You can use standard Docker Compose commands to manage your OpenMates environment. Remember to include the optional override file if you are using it.

-   **View logs:**
    ```bash
    # View logs for all services
    docker compose --env-file .env -f backend/core/docker-compose.yml logs -f

    # View logs for a specific service (e.g., api)
    docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api
    ```
-   **Stop all services:**
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml down
    ```
-   **Restart a specific service:**
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml restart api
    ```

### Troubleshooting

**Complete reset (clears cache and rebuilds everything):**
```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && docker volume rm openmates-cache-data && docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build && docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

*Use this command when normal restarts don't resolve issues, or when you want to ensure a completely clean state. This will:*
- *Stop all services*
- *Remove cached data that might be causing issues*
- *Rebuild all Docker images from scratch*
- *Start all services with fresh builds*

## Design Guidelines

[![Design Guidelines header image](./docs/images/designguidelines_header.png)](./docs/designguidelines/README.md)

A great UX & UI design that makes OpenMates accessible to everyone and not just tech enthusiasts is one of the key differences from other AI agent software.

[Show design guidelines](./docs/designguidelines/README.md)

## Architecture

[![Architecture header image](./docs/images/architecture_header.png)](./docs/architecture/README.md)

OpenMates is a web app, which is built with a privacy focus, separation of concerns, easy setup and scalability in mind. The code is currently still a bit of a work-in-progress mess. I am working on it.

[Show architecture](./docs/architecture/README.md)

## Code quality

The code is currently more chaotic and not as well commented / documented as I want it to be. But this is a temporary state and does not reflect what I consider well-written and organized code.
Because this is a pretty big project in terms of scope / functionality / parts to implement - and because I find it pretty obvious at this point that AI-assisted coding is here to stay and will only become more relevant and not less - I switched during the development process from writing most of the code myself to instead collaborating with AI together to plan the architecture, todos and let AI do most of the coding. My experiences here ranged from being blown away by AI having taught me a lot new about software development, saved me a lot of time, built better code than what I would have come up with and made a project of this scale even possible to start as a single person - up to me yelling at the AI for making stupid suggestions. However, while in some instances one can fairly blame the LLM models themselves - most of the blame goes to how badly the existing AI coding extensions and VScode forks like Cursor and Windsurf are implementing existing LLMs. After all: an LLM can’t consider context it doesn’t know about. Resulting in none of them being able so far to deliver a high-quality workflow that is consistent over weeks. All of the extensions and AI VScode forks I tried (and I tried easily 6-7 of them) are on various degrees of shitty, with some being less shitty than others (especially if one knows how to give the LLM additional code context to try to fix the mistakes of the developers who built the extensions and forks). But still, they are more valuable than in the way and I find it important to instead of rejecting AI-assisted coding - instead to learn what others do badly and how it should be done better instead. Which also led me to lots of ideas for building a custom VScode extension for OpenMates in the coming months. But that’s a topic for another day.​​​​​​​​​​​​​​​​
