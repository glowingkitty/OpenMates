# 🧠 OpenMates — CLI + SDK Architecture

> **Status:** Feature not yet fully implemented

## Overview

A single package (`openmates`) available for both **Python (PyPI)** and **Node.js (npm)**.  

### Purpose & Use Cases
The CLI serves multiple purposes:
- **Install & manage self-hosted instances** with Docker setup
- **Enable remote access** to servers via web app
- **Interact with AI** through terminal (ask questions, manage chats)
- **Programmatic SDK** for both Python and JavaScript developers

### What It Provides

**SDK Access:**
```python
import openmates
from openmates import OpenMates
```
```javascript
import { OpenMates } from "openmates";
```

**CLI Commands:**
```bash
openmates server install
openmates chat "Hello"
openmates apps ai ask "What is Docker?"
```

### What It Does NOT Include
The CLI is **not designed for full chat management** — a terminal is not ideal for browsing and managing conversation history. For that, use the web app and connect it to your machine using the `openmates remote-access` command. The CLI provides basic chat interaction but is optimized for quick queries and server management.

---

## 📦 Folder Structure

### Python (`openmates/`)

```
openmates/
├── openmates/
│   ├── __init__.py        # SDK entry
│   ├── api.py             # API client logic
│   ├── cli.py             # CLI entrypoint (Click)
│   └── server/            # Docker setup helpers
├── pyproject.toml
```

### Node.js (`openmates/`)

```
openmates/
├── src/
│   ├── index.js           # SDK entry
│   ├── cli.js             # CLI entrypoint (Commander)
│   └── server.js          # Docker setup helpers
├── package.json
```
---

## 🐍 Python — `pyproject.toml`
```toml
[project]
name = "openmates"
version = "0.1.0"
description = "OpenMates SDK and CLI"
dependencies = ["requests", "click"]

[project.scripts]
openmates = "openmates.cli:cli"
```

**After pip install openmates:**
- `import openmates` → SDK available in code
- `openmates` → CLI command available globally

---

## 🟦 Node.js — `package.json`
```json
{
  "name": "openmates",
  "version": "0.1.0",
  "description": "OpenMates SDK and CLI",
  "type": "module",
  "main": "src/index.js",
  "bin": {
    "openmates": "./src/cli.js"
  },
  "dependencies": {
    "commander": "^12.0.0",
    "axios": "^1.6.7"
  }
}
```

**After npm install -g openmates:**
- `import { OpenMates } from "openmates"` → SDK available in code
- `openmates` → CLI command available globally

---

## 💻 Example CLI Commands
```bash
openmates server install --env-path ./config/dev.env --auto-setup
openmates server logs --follow
openmates chat "What is docker?" --model claude-4.5-sonnet
```

---

## 💡 General Implementation Ideas

### Authentication & UI
- **Login via magic URL / QR code** from other devices for easy setup
- **Consider using Textual** (Python-based TUI) instead of Ink (JS-based) for better security and consistency
- **Use Catimg** for displaying QR codes or graphics in terminal

### System Monitoring (Optional Feature)
Include in every request when connected to a server:
- Current CPU usage
- Memory usage
- Disk usage
- Ports in use
- Docker containers running
- npm and Python scripts running

This can be always-on or optional if requested in preprocessing.

---

## ⚙️ Key Design Principles
- **Subcommands** for actions (install, logs, update, chat, etc.)
- **Flags (--)** for configuration and modifiers (--env-path, --auto-setup)
- **One package** handles both CLI and SDK
- **Optional / lazy dependencies** for features like Docker setup
- **Consistent naming**: openmates (PyPI/npm) → openmates (Python import)
- **Auto-update checks** on CLI startup with update suggestions
- **Progressive disclosure**: Basic features by default, advanced features opt-in

---

## ✅ Result
Developers can:

```bash
pip install openmates
openmates server install
```

or

```bash
npm install -g openmates
openmates server install
```

and in code:

```python
from openmates import OpenMates
```

or

```javascript
import { OpenMates } from "openmates";
```


---

## 🖥️ CLI Commands Reference

### Main Interface

#### `openmates`
**Functionality:** Opens the main interface with options for server management and authentication. If already logged in, displays available CLI commands.

**Description:** Entry point that provides an interactive menu for server setup, login, and command discovery.

---

### Server Management

#### `openmates server install [--env-path PATH]`
**Functionality:** Installs and configures the OpenMates server with Docker setup.

**Parameters:**
- `--env-path PATH` *(optional)*: Path to environment configuration file (default: `./config/dev.env`)

**Description:** Sets up the complete OpenMates server stack using Docker containers with automatic configuration.

---

#### `openmates server logs [--container CONTAINER_NAME] [--follow]`
**Functionality:** Displays server logs for monitoring and debugging.

**Parameters:**
- `--container CONTAINER_NAME` *(optional)*: Show logs for specific Docker container only
- `--follow` *(optional)*: Follow log output in real-time (like `tail -f`)

**Description:** Provides access to server logs with optional filtering by container and real-time monitoring.

---

#### `openmates server start`
**Functionality:** Starts the OpenMates server if not already running.

**Description:** Ensures the server is running and accessible.

---

#### `openmates server stop`
**Functionality:** Stops the OpenMates server if it is running.

**Description:** Stops the server if it is running.

---

#### `openmates server restart`
**Functionality:** Restarts the OpenMates server if it is running.

**Description:** Restarts the server if it is running.

---

#### `openmates server update`
**Functionality:** Updates the OpenMates server to the latest version.

**Description:** Updates the server components to the latest version. The CLI automatically checks for updates on startup and suggests installing them. This command pulls the latest Docker images and restarts the services.

---

#### `openmates server reset`
**Functionality:** Resets the OpenMates server with data deletion options.

**Description:** 
Resets the server by deleting user data and optionally configuration data. 

**⚠️ Safety Measures:**
- Displays clear warning with consequences checklist
- Provides backup advice before proceeding
- Requires user to enter confirmation phrase to proceed
- Cannot be undone without backups

**Parameters:**
- `--delete-user-data-only` *(optional)*: Only delete the user data, but keep the config data

**Use Cases:**
- Full reset: Deletes all user data + OpenMates configs (fresh start)
- Partial reset: Deletes only user data, keeps server configuration

---

### Authentication

#### `openmates login`
**Functionality:** Initiates authentication flow using magic link.

**Description:** Starts the secure login process via magic link sent to your registered email address.

---

### Chat (Outside App Architecture)

**Architectural Note:** Chat commands operate outside the app-based architecture. They manage persistent conversations that show up in the web app and can leverage apps on-demand during conversations. This is distinct from app-specific commands which directly invoke app skills.

Same chats as they show up in the web app. Allows to continue existing chats or start new ones. Requires decrypting and encrypting chats. Also allows to delete chats.

#### `openmates chat "Your message" [--chat-id CHAT_ID]`
**Functionality:** Manages chat conversations with the AI agent. Allows to continue existing chats or start new ones. Requires decrypting and encrypting chats. Also allows to delete chats. Returns chat id together with the assistant's response.

**Parameters:**
- `--chat-id CHAT_ID` *(optional)*: Continue existing chat session; if omitted, starts new chat

**Description:** 
- **New chat**: Starts a new conversation and returns chat ID
- **Existing chat**: Adds message to existing conversation and loads full chat history

---

#### `openmates chat delete [--chat-id CHAT_ID]`
**Functionality:** Deletes a chat.

**Parameters:**
- `--chat-id CHAT_ID` *(required)*: Delete specific chat

**Description:** Deletes a chat.

---

### Apps (App-Based Architecture)

**Architectural Note:** All apps follow the consistent pattern `openmates apps [app-name] [skill-name]`. This includes the base "AI" app which provides core question-answering functionality.

Every app can be used via CLI using the `openmates apps [app-name] [skill-name]` pattern. 

> **Note:** Support for reading and writing app settings and memories should also be added.

---

#### `openmates apps ai ask "Your question here" [--files FILEPATH1,FILEPATH2,...]`
**Functionality:** Sends a question to the AI agent using the base AI app's ask skill.

**Parameters:**
- `--files FILEPATH1,FILEPATH2,...` *(optional)*: Comma-separated list of filepaths to include in full context
- `--model MODEL` *(optional)*: Model to use for the question
- `--temperature TEMPERATURE` *(optional)*: Temperature for the question

**Description:** Direct AI interaction with the ability to include local files for context-aware responses. This is the base app which OpenMates uses to answer questions. Does not store any chats or conversations. For accessing chat history, use the `openmates chat` command instead.

**Why `apps ai ask` instead of just `ask`?**  
This naming follows the app-based architecture where "AI" is the base app. Keeping the consistent `openmates apps [app-name] [skill-name]` pattern makes the architecture clear and extensible.

---

#### `openmates apps web search "search query"`
**Functionality:** Performs web search using the web app's search skill.

**Description:** Uses the search skill of the web application to return raw search results without additional LLM processing. Multiple search queries can be provided as a list like this: `openmates apps web search "search query1" "search query2" "search query3"`.

> **Note:** We need to keep in mind that the input structure needs to be reusable across app skills and also consider that app skills have more than one input parameter - which still needs to work when we trigger the execution of multiple skill uses in one command.

---

### Remote Access

#### `openmates remote-access start [--full-access] [--dev-server]`
**Functionality:** Enables remote access for web app to interact with the server's file system and execute commands.

**Description:** 
Allows the OpenMates web app to access folders, files, and execute commands on the server. The security model is determined by the flags used when starting the service.

**Parameters:**
- `--full-access` *(optional)*: Allows full machine control beyond the current folder
- `--dev-server` *(optional)*: Enables autonomous access without command confirmation (development mode)

**Security Model:**

| Mode | Access Scope | Command Confirmation | Use Case |
|------|-------------|---------------------|----------|
| **Default** (no flags) | Current folder + subfolders only | ✅ Required for all operations | Production servers, safe default |
| `--full-access` | Full machine access | ✅ Required for all operations | Production servers needing broader access |
| `--dev-server` | Current folder + subfolders only | ❌ Autonomous execution | Development/temporary environments |
| `--full-access --dev-server` | Full machine access | ❌ Autonomous execution | ⚠️ Use with extreme caution |

**Command Confirmations (when required):**
When not in `--dev-server` mode, the user must explicitly approve each command that:
- Writes, deletes, or moves files
- Starts, installs, or uninstalls services
- Updates services
- Makes any potentially destructive changes

**Read operations generally do NOT require confirmation**, as reading is non-destructive.

Each confirmation includes a detailed explanation of the consequences before execution.

**Sensitive Files Protection:**
Certain file types that commonly contain secrets are **never read automatically**, even when the LLM requests them:
- Environment files (`.env`, `.env.*`, `.envrc`)
- Private keys (`.pem`, `.key`, `.p12`, `.pfx`, `.keystore`)
- SSH keys (`id_rsa`, `id_ed25519`, `id_dsa`, `authorized_keys`, `known_hosts`)
- Cloud credentials (`~/.aws/credentials`, `~/.config/gcloud/`, `~/.azure/`)
- Database connection files (`.pgpass`, `.my.cnf`, `database.yml` with credentials)
- Password manager files (`.kdbx`, `1Password.sqlite`)
- API key files (`secrets.json`, `credentials.json`, `*.credentials`)
- Git credentials (`.git-credentials`, `.netrc`)

**When User Explicitly Provides Sensitive File Path:**
If a user explicitly mentions a sensitive file path, the system will:
1. Display a clear warning about the risks (but not block the action)
2. Advise the user to rotate/change credentials after this session
3. Proceed with reading the file as requested
4. Log this action for audit purposes

Example warning displayed before file contents:
> ⚠️ **WARNING: This file likely contains sensitive credentials**
> 
> File: `.env`
> 
> **Important:**
> - API keys and passwords will be shared with the LLM
> - Credentials may be cached or logged by the AI provider
> - **Rotate all credentials in this file after this session**
> 
> Reading file as requested...

**Use Cases:**
- **Production servers (default)**: Secure folder-scoped access with explicit approval workflow
- **Production servers (--full-access)**: Broader access when needed, still requires confirmation
- **E2B VMs (--dev-server)**: Auto-installed and logged in for executing untrusted code autonomously
- **Development environments (--dev-server)**: Fast iteration without constant confirmations

**Note:** The CLI is automatically installed and logged into the user account on e2b VMs to execute untrusted code safely while allowing user interaction via the web interface.

---

## 🔒 Security Principles

**Default Settings:** Conservative and limited access for production safety
**Opt-in Features:** Full access and autonomous operation require explicit flags
**Confirmation Required:** All potentially harmful operations require user confirmation by default