"""SMTP transport for the disposable GitHub CI mailbox only."""

import asyncio
import base64
from email.message import EmailMessage
from email.utils import formataddr
import mimetypes
import os
import re
import smtplib
from typing import Any, Dict, Optional

from backend.core.api.app.services.email.base_provider import BaseEmailProvider


class CiMailProvider(BaseEmailProvider):
    """Deliver rendered mail to Mailpit without granting external mail access."""

    def __init__(self) -> None:
        required = {
            "CI": "true",
            "OPENMATES_CI_ISOLATED": "1",
            "OPENMATES_CI_MAIL_CAPTURE": "1",
            "SERVER_ENVIRONMENT": "development",
        }
        if any(os.environ.get(name) != value for name, value in required.items()):
            raise RuntimeError("CI mail capture requires the isolated development runner")

    def get_provider_name(self) -> str:
        return "CI Mailpit"

    async def send_email(
        self,
        sender_name: str,
        sender_email: str,
        recipient_email: str,
        recipient_name: str,
        subject: str,
        html_content: str,
        plain_text_content: str,
        email_headers: Dict[str, Any],
        attachments: Optional[list],
    ) -> bool:
        # A misrouted CI message must fail before opening an SMTP connection.
        if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@example\.com", recipient_email, re.IGNORECASE):
            raise ValueError("CI mail capture accepts example.com recipients only")

        message = EmailMessage()
        message["From"] = formataddr((sender_name, sender_email))
        message["To"] = formataddr((recipient_name, recipient_email))
        message["Subject"] = subject
        for name, value in email_headers.items():
            message[name] = value
        message.set_content(plain_text_content)
        message.add_alternative(html_content, subtype="html")
        for attachment in attachments or []:
            if attachment.get("inline") or attachment.get("contentId"):
                raise ValueError("CI mail capture does not support inline attachments")
            filename = attachment["filename"]
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            maintype, subtype = mime_type.split("/", 1)
            message.add_attachment(
                base64.b64decode(attachment["content"], validate=True),
                maintype=maintype,
                subtype=subtype,
                filename=filename,
            )

        def deliver() -> None:
            with smtplib.SMTP("mailpit", 1025, timeout=10) as smtp:
                smtp.send_message(message, from_addr=sender_email, to_addrs=[recipient_email])

        await asyncio.to_thread(deliver)
        return True
