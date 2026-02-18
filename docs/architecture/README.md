# Architecture

![Architecture header image](../images/architecture_header.png)

## Quick links

- **Servers**: [servers.md](servers.md)
- **Signup & login**: [signup_login.md](signup_login.md)
- **Security**: [security.md](security.md)
- **Message processing**: [message_processing.md](message_processing.md)
- **Message parsing**: [message_parsing.md](message_parsing.md)
- **Embeds**: [embeds.md](embeds.md)
- **AI model selection**: [ai_model_selection.md](ai_model_selection.md)
- **Pricing**: [pricing.md](pricing.md)
- **Translations**: [translations.md](translations.md)
- **Sync**: [sync.md](sync.md)
- **Share a chat**: [share_chat.md](share_chat.md)
- **File Upload**: [file_upload.md](file_upload.md)
- **Creator Program**: [creator_program.md](creator_program.md)

## Apps

- **Apps overview**: [apps/README.md](apps/README.md)
- **App skills**: [apps/app_skills.md](apps/app_skills.md)
- **Code**: [apps/code.md](apps/code.md)
- **Events**: [apps/events.md](apps/events.md)
- **Fitness**: [apps/fitness.md](apps/fitness.md)
- **Images**: [apps/images.md](apps/images.md)
- **Mail**: [apps/mail.md](apps/mail.md)
- **Music**: [apps/music.md](apps/music.md)
- **News**: [apps/news.md](apps/news.md)
- **Slides**: [apps/slides.md](apps/slides.md)
- **Study**: [apps/study.md](apps/study.md)
- **Travel**: [apps/travel.md](apps/travel.md)
- **Videos**: [apps/videos.md](apps/videos.md)
- **Web**: [apps/web.md](apps/web.md)
- **Jobs**: [apps/jobs.md](apps/jobs.md)
- **Docs**: [apps/docs.md](apps/docs.md)
- **PDF**: [apps/pdf.md](apps/pdf.md)
- **Sheets**: [apps/sheets.md](apps/sheets.md)

## Servers

### Backend

- Docker compose setup
  - api docker (FastAPI)
  - cms dockers (Directus & PostgreSQL)
  - task-worker dockers (celery worker & scheduler)
  - cache docker (Dragonfly)
  - logging dockers (Grafana, Loki, Prometheus)
  - app-ai docker & other docker containers for each app

### Frontend

- svelte web app
  - can run either directly via docker-compose (default) or via pnpm dev mode for better debugging/ live code updates (only relevant for contributors)

[Click here to read more](servers.md)

## Signup & login architecture

### Current signup & login implementation

- user signup & login via email + password + 2FA OTP (mandatory)

### Signup & login plans for improvements

- multiple signup / login options:
  - email + passkey (recommended)
  - email + hardware key / yubikey
  - email + password (requires additional 2FA OTP to enhance security)

[Click here to read more](signup_login.md)

## Security architecture

### Current Security

- **Zero-Knowledge Architecture**: Encryption and decryption of chats and sensitive user data (app settings, memories, etc.) happen on the user device, not on the server.
- **Vault Key Management**: User encryption keys are wrapped and stored in HashiCorp Vault, but the server never has access to the plaintext keys required to decrypt user content.
- **Device Storage**: User devices store chats in a local encrypted database (IndexedDB) for fast access and offline capability.
- **API Key Security**: Third-party API keys are securely stored in HashiCorp Vault.

[Click here to read more](security.md)

## Processing architecture of messages

- user sends message in web app
- fastapi docker receives message via websocket
- after authentication message is forwarded to celery to execute via the AI app / Ask skill the request
- billing-precheck
  - checks if user has enough minimum credits for request
- pre-processing (by default using cheap Mistral API on EU servers)
  - detect harmful / illegal request (and reject if clearly detected)
  - generate chat title
  - detect complexity level
  - detect temperature (creativity level needed)
  - match category to forward to right mate
  - user message is encrypted on user device and sent to server for zero-knowledge storage
- main-processing (model/provider depends on complexity level)
  - process request via LLM
  - if app skill or app focus mode is requested, the system executes it via tool calling
  - stream back response back to frontend via websocket (if chat is open on device, else wait for completed message to notify about completed message)
- post-processing (by default using cheap Mistral API on EU servers)
  - check harmfulness & misuse for scams / causing harm risk
  - based on last user question and assistant response: suggest 6 possible follow up questions which are shown to user, which user can click on to add them to message input field
  - assistant response is encrypted on user device and sent to server for zero-knowledge storage
- billing
  - user is charged in credits for main processing (for input tokens and output tokens)
