# Prompt Injection Protection

> Prompt injection attack protection strategy for OpenMates. Rebuff (protectai/rebuff) was archived May 16, 2025. This document outlines recommended alternatives.

## Attack scenarios

- App skill is processing text which contains malicious instructions targeting the assistant (website text, video transcript, emails, etc.)
- user uploads PDFs or code snippets which unknown to them contains malicious instructions targeting the assistant

## Defense Strategies

We implement **defense-in-depth** with multiple layers.

- LLM processing of data which come from App skills (website text, video transcript, emails, etc.) -> assume they include malicious prompt injection attempts targeting the assistant, scan with prompt who's only purpose is to detect prompt injection attempts and attempt to either remove prompt injection prompt or block content entirely
- certain sensitive app skills always require manual confirmation of user to be executed (overwrite option can be considered, but only in combination with clear warning of security risks)
- **CLI terminal command blocking**: The CLI prevents the LLM from executing arbitrary shell commands to read files and instead provides safe file-reading with zero-knowledge processing. See [CLI Blocking of Terminal Commands for File Reading](./cli_package.md#-security-principles) in the CLI Package documentation for implementation details.
- we always strip all url parameters from urls, like `/?secrets_from_user_device=...` before processing them with the assistant, to prevent attacks involving url parameters
- ... more to be added
