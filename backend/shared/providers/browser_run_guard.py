# backend/shared/providers/browser_run_guard.py
#
# Run-level guard for Browse: OpenMates itself only does normal single-user
# actions at human speed on live sites. Mass or abusive actions (many form
# submissions, sign-ups, comments or logins in one run, or submissions faster
# than a person could make them) stop the run with a polite explanation.
# Reading pages, scrolling, choosing options and one normal form fill pass.

"""Deterministic guard against mass or repetitive actions in one Browse run."""

from __future__ import annotations

import time
from typing import Any

from backend.shared.providers.browser_planner import control_index, plain_action

MAX_SUBMISSIONS_PER_RUN = 5
MAX_SUBMISSIONS_PER_PLAN = 3
MAX_SAME_CONTROL_SUBMISSIONS = 3
MIN_SECONDS_BETWEEN_SUBMISSIONS = 1.0

MASS_ACTION_MESSAGE = (
    "You probably do own this site, but Browse only does normal single-user actions at human speed on "
    "live websites, so it cannot run mass or abusive actions such as mass comments, sign-ups, password "
    "guessing or flooding. Such tests currently run only against localhost, a local dev environment or a "
    "locally run staging copy. I can help you set that up."
)


class RunGuard:
    """Counts submitting actions across one run and refuses mass or too-fast repetition."""

    def __init__(self) -> None:
        self.submissions = 0
        self.per_control: dict[str, int] = {}
        self.last_submission_at: float | None = None

    @staticmethod
    def _submits(actions: list[dict[str, Any]], observation: dict[str, Any]) -> list[dict[str, Any]]:
        return [action for action in actions if not plain_action(action, observation) and action["kind"] != "goto"]

    def check(self, actions: list[dict[str, Any]], observation: dict[str, Any], now: float | None = None) -> str | None:
        """Return the refusal message for a plan that would be mass or too-fast, else None (and count it)."""
        submits = self._submits(actions, observation)
        if not submits:
            return None
        now = time.monotonic() if now is None else now
        controls = control_index(observation)
        keys = [f"{observation.get('url', '')}|{controls.get(str(a.get('target')), {}).get('label', '')}" for a in submits]
        too_fast = (
            self.last_submission_at is not None
            and now - self.last_submission_at < MIN_SECONDS_BETWEEN_SUBMISSIONS
        )
        repeated = any(self.per_control.get(key, 0) + keys.count(key) > MAX_SAME_CONTROL_SUBMISSIONS for key in keys)
        if (
            len(submits) > MAX_SUBMISSIONS_PER_PLAN
            or self.submissions + len(submits) > MAX_SUBMISSIONS_PER_RUN
            or repeated
            or too_fast
        ):
            return MASS_ACTION_MESSAGE
        self.submissions += len(submits)
        self.last_submission_at = now
        for key in keys:
            self.per_control[key] = self.per_control.get(key, 0) + 1
        return None
