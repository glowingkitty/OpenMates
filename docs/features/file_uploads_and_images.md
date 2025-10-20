## File & Image Uploads — Notes (Planned)

Status: Not yet implemented

- Default: on selection, immediately background-upload to the upload server and trigger safety processing (scan + prep). Goal: by the time the user presses Send, files are already safe and server-ready, avoiding any send-time delay.
- Exception: for users who frequently abandon attachments, defer background upload and scanning until Send; still block sending if scan fails.
- Use temporary storage with short TTL, signed URLs, and client/server type/size checks. Thresholds/config TBD.
- Placeholder only; fuller spec will follow in architecture docs when implementation starts.

