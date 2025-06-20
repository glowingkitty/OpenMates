# OpenMates

[![OpenMates header image](./docs/images/openmates_header.png)](https://openmates.org)

Digital teammates for everyone. With a focus on everyday use cases for private and work life, great UX design, privacy and provider independence.

> *The following instructions (as well as the code) are still an early prototype and will be improved and extended in the coming weeks. Keep in mind the current release of OpenMates is for developers and early testers only and many features are still missing. If you prefer to wait for a more stable release (Current release estimate: July / August), join our Discord group to be informed when a more stable release of OpenMates is published.*

## What is OpenMates?

OpenMates is a web app that makes AI agents accessible to everyone, which can not only answer questions but also use various apps. Apps like Web, Travel, Health, Code, Calendar and many more. Need to use external providers to search for train connections or search for available doctor appointments that don’t collide with your calendar? That’s what app skills are for. And app focuses temporarily change the system prompt for a conversation to focus the chat on a specific goal, like planning a new software project, getting career advice and much more - all without you having to be an expert in AI prompt engineering.

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
    This command starts all the necessary background services (like the API, database, etc.). Use the optional `docker-compose.override.yml` file to also expose the web interfaces for Directus (CMS) and Grafana (Monitoring).
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
    ```
    - Directus will be available at `http://localhost:8055`
    - Grafana will be available at `http://localhost:3000`

-   **2. Start the frontend service (for development):**
    This command starts the web app with hot-reloading, which is ideal for development.
    ```bash
    pnpm --filter web_app dev --host 0.0.0.0 --port 5174
    ```
    *Note: The first time you access the web app, it may take up to a minute to load as Svelte builds the necessary files.*

-   **3. Check for your invite code:**
    The initial setup generates an invite code for the first user. Check the logs of the `cms-setup` container to find it.
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml logs cms-setup
    ```
-   **4. Access the web app:**
    Open [http://localhost:5174](http://localhost:5174) in your browser. Click "Sign Up" and use the invite code to create your account.

### Manage the services

You can use standard Docker Compose commands to manage your OpenMates environment. Remember to include the optional override file if you are using it.

-   **View logs:**
    ```bash
    # View logs for all services
    docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml logs -f

    # View logs for a specific service (e.g., api)
    docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml logs -f api
    ```
-   **Stop all services:**
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down
    ```
-   **Restart a specific service:**
    ```bash
    docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml restart api
    ```

## Design Guidelines

[![Design Guidelines header image](./docs/images/designguidelines_header.png)](./docs/designguidelines/README.md)

A great UX & UI design that makes OpenMates accessible to everyone and not just tech enthusiasts is one of the key differences from other AI agent software.

[Show design guidelines](./docs/designguidelines/README.md)

## Architecture

[![Architecture header image](./docs/images/architecture_header.png)](./docs/architecture/README.md)

OpenMates is a web app, which is built with a privacy focus, separation of concerns, easy setup and scalability in mind. The code is currently still a bit of a work-in-progress mess. I am working on it.

[Show architecture](./docs/architecture/README.md)

## Contribute

[![Contribute header image](./docs/images/contributing_header.png)](./docs/contributing.md)

After many months of work I have open-sourced this project, so that this personal project can grow into a larger community project. Now I am looking forward to seeing how the project will evolve.

[Learn how to contribute](./docs/contributing.md)

## Code quality

The code is currently more chaotic and not as well commented / documented as I want it to be. But this is a temporary state and does not reflect what I consider well-written and organized code.
Because this is a pretty big project in terms of scope / functionality / parts to implement - and because I find it pretty obvious at this point that AI-assisted coding is here to stay and will only become more relevant and not less - I switched during the development process from writing most of the code myself to instead collaborating with AI together to plan the architecture, todos and let AI do most of the coding. My experiences here ranged from being blown away by AI having taught me a lot new about software development, saved me a lot of time, built better code than what I would have come up with and made a project of this scale even possible to start as a single person - up to me yelling at the AI for making stupid suggestions. However, while in some instances one can fairly blame the LLM models themselves - most of the blame goes to how badly the existing AI coding extensions and VScode forks like Cursor and Windsurf are implementing existing LLMs. After all: an LLM can’t consider context it doesn’t know about. Resulting in none of them being able so far to deliver a high-quality workflow that is consistent over weeks. All of the extensions and AI VScode forks I tried (and I tried easily 6-7 of them) are on various degrees of shitty, with some being less shitty than others (especially if one knows how to give the LLM additional code context to try to fix the mistakes of the developers who built the extensions and forks). But still, they are more valuable than in the way and I find it important to instead of rejecting AI-assisted coding - instead to learn what others do badly and how it should be done better instead. Which also led me to lots of ideas for building a custom VScode extension for OpenMates in the coming months. But that’s a topic for another day.​​​​​​​​​​​​​​​​
