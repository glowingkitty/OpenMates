"""Team direct-email invite routing helpers.

TeamInviteEmailService keeps invite delivery separate from membership creation.
It stores only hashed routing identifiers plus encrypted display hints in Directus.
The complete invite URL has a client-only fragment secret, so the backend must
never generate or send an incomplete replacement URL. The inviter client handles
sharing the complete link; response shape avoids account-existence signals.

Spec: docs/specs/teams-v1/spec.yml
"""

from __future__ import annotations

import base64
import hashlib
import time
from typing import Any, Protocol


class TeamInviteEmailSender(Protocol):
    async def send_team_invite_email(self, *, to_email: str, accept_url: str, role: str, domain: str) -> bool:
        """Send a team invite email without logging private recipient data."""


def normalize_invite_email(email: str) -> str:
    return email.strip().lower()


def hash_invite_email(email: str) -> str:
    return base64.b64encode(hashlib.sha256(normalize_invite_email(email).encode()).digest()).decode("utf-8")


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TeamInviteEmailService:
    def __init__(self, team_methods: Any, email_sender: TeamInviteEmailSender | None = None) -> None:
        self.team_methods = team_methods
        self.email_sender = email_sender

    async def create_email_invite(
        self,
        *,
        team_id: str,
        inviter_user_id: str,
        recipient_email: str,
        invite_id: str,
        role: str,
        domain: str,
        encrypted_recipient_hint: str | None = None,
        encrypted_invite_team_key: str | None = None,
        invite_key_kdf_context: dict[str, Any] | None = None,
        expires_at: int | None = None,
        created_at: int | None = None,
    ) -> dict[str, Any] | None:
        now = int(created_at or time.time())
        invite = await self.team_methods.create_invite(
            team_id,
            inviter_user_id,
            {
                "invite_id": invite_id,
                "role": role,
                "hashed_recipient_email": hash_invite_email(recipient_email),
                "encrypted_recipient_hint": encrypted_recipient_hint,
                "encrypted_invite_team_key": encrypted_invite_team_key,
                "invite_key_kdf_context": invite_key_kdf_context,
                "one_time_token_hash": None,
                "sent_at": None,
                "expires_at": expires_at,
                "created_at": now,
            },
        )
        if not invite:
            return None
        return {
            "invite_id": invite.get("invite_id"),
            "role": invite.get("role"),
            "status": invite.get("status"),
            "delivery_status": "client_share_required",
            "domain": domain,
            "domain_reminder": f"Recipient must accept with an OpenMates account on {domain}.",
        }
