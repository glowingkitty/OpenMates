---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-11
claims:
  - id: user-guide-file-uploads-source
    type: unit
    claim: File upload guidance is grounded in current embed upload and fullscreen renderer sources.
    file: scripts/tests/test_user_guide_product_docs_claims.py
    assertion: user-guide-file-uploads-source
---

# File Uploads

> Send images, PDFs, audio files, code, and text files in your chats. Uploads are handled as encrypted embed content with previews where supported.

## What It Does

You can upload files directly into a chat. Your digital team mate can then view, analyze, and discuss the content with you. All uploaded files are encrypted so only you can access them.

## Supported File Types

- **Images** — JPEG, PNG, WebP, GIF, HEIC, BMP, TIFF, SVG
- **PDFs** — documents, reports, scanned pages
- **Audio** — voice recordings and audio files (transcription available via the Audio app)
- **Code and text files** — Python, JavaScript, TypeScript, HTML, CSS, JSON, Java, C/C++, Rust, Go, Ruby, PHP, Swift, Kotlin, SQL, Markdown, YAML, shell scripts, Dockerfiles, and more

## How to Use It

1. Click the attachment icon in the message input field
2. Select a file from your device
3. The file is uploaded and stored as encrypted embed content
4. Send your message — your digital team mate can now see and discuss the file

You can also drag and drop files into the chat.

## What Happens Behind the Scenes

- **Encryption** -- upload payloads include encryption material so files can be opened by your devices.
- **Image safety metadata** -- supported image uploads can include AI/content-detection metadata.
- **Previews** -- supported image and PDF uploads can be opened in preview or fullscreen views.

## Storage

- File storage and retention follow the current account storage settings and billing rules.
- Deleting a chat can remove the file references attached to that chat.

## Tips

- Upload a photo of a document to have your digital team mate read and summarize it
- Send audio recordings to get them transcribed
- Large files may take a moment to upload and process
- Files are stored securely and synced across all your devices

## Related

- [Images](apps/images.md) — generate and search for images
- [PDF](apps/pdf.md) — read and search PDF documents
- [Sharing](sharing.md) — how sharing works with encrypted content
