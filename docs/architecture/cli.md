# CLI (command line interface) architecture 

> Feature not yet implemented

The CLIs has multiple purpose / usecases:
- install & manage self hosted instance
- remote access server via web app

That said, the CLI is NOT supposed to give access to the chats of a user, since a CLI is a terrible way to interact with chats.

## General ideas

- login via magic url / QR code from other device
- consider using Textual (python based) insteaf of Ink (js based) -> better security? also considering recent npm phishing attack?
- use Catimg for showing QR code or graphics?
- include in every request when connected to a server the current cpu usage, memory usage, disk usage, ports used, docker containers running and maybe also npm and python scripts running? either always or optional if requested in preprocessing?

## Install & manage self hosted instance

The CLI should make it easy to install and manage a self hosted instance of OpenMates. With these menu points / features:

- Install (or Uninstall, if already installed), also via --server --install or --s --i directly?
- Restart (shutdown docker compose setup, optionally delete cached data, restart docker compose setup)
- Update (auto checks for updates on cli startup, and suggests to install them)
- Reset (deletes all user data and optionally also all openmates configs, after clear warning with user being required to enter confirmation phrase after reading checklist of consequences & advice about backups)
- Logs (show docker compose logs)

And more can be added over time.

## Remote access server via CLI

Allows OpenMates web app to access folders and files on the server. When the service starts, user will be asked "Is this a production server? Or would it be very bad if data are deleted by accident? If so: Turn on 'Safety mode', which requires excplicit confirmation of every command that writes, deletes or moves files or starts, installs or deinstalls services or updates services - including an explainer of the consequences of the action. For dev servers / temp machines OpenMates can also operate more autonomously without requiring confirmation every time.

Once the CLI has started, the user can connect to the server via the web app to interact with files. The CLI will also be auto installed & logged in to the user account on e2b VMs to execute untrusted code on the machine but also allow user to interact with the VN using the web interface.
