# OpenMates

[![OpenMates header image](docs/images/openmates_header.jpg)](https://openmates.org)

Digital team mates for everyone. With a focus on everyday usecases for private and work life, great UX design, privacy and provider independence.

## What is OpenMates?

OpenMates is a web app that makes AI agents accessible to everyone, which can not only answer questions but also use various apps. Apps like Web, Travel, Health, Code, Calendar and many more. Need to use external providers to search for train connections or search for available doctor appointments that don't collide with your calendar? Thats what app skills are for. And app focuses temporarily change the systemprompt for a conversation to focus the chat on a specific goal, like planning a new software project, getting career advice and much more - all without you having to be an expert in AI prompt engineering.

> _The following instructions (as well as the code) are still an early prototype and will be improved and extended in the coming weeks._

## Self hosted setup

![Self hosted setup header image](docs/images/selfhostedsetup_header.jpg)

### Requirements

- docker & docker compose installed

### Setup

1. Clone the repo
   - `git clone https://github.com/glowingkitty/OpenMates`
2. Prepare `.env`
   - rename `example.env` to `.env`
   - add your API keys in `.env`

### Start

- open the OpenMates folder in your terminal
- `docker compose --env-file .env up`
- check the `cms-setup` logs for a generated invite code
- open [http://localhost:5174](http://localhost:5174), click signup and use the invite code to signup for an account and to start using OpenMates

## Design Guidelines

[![Design Guidelines header image](docs/images/designguidelines_header.jpg)](./docs/designguidelines.md)

A great UX & UI design that makes OpenMates accessible to everyone and not just tech enthusiasts is one of the key differences to other AI agents software.

[Show design guidelines](./docs/designguidelines.md)

## Architecture

[![Architecture header image](docs/images/architecture_header.jpg)](./docs/architecture.md)

OpenMates is a web app, which is built with a privacy focus, separation of concerns, easy setup and scalability in mind. The code is currently still a bit of a work in progress mess. I am working on it.

[Show architecture](./docs/architecture.md)

## Contribute

[![Contribute header image](docs/images/contribute_header.jpg)](./docs/contributing.md)

After many months of work I have open sourced this project, so that this personal project can grow into a larger community project. Now I am looking forward to see how the project will evolve.

[Learn how to contribute](./docs/contributing.md)
