"""Dependency-free price of one generated music track.

``backend/apps/music/app.yml`` declares the same number for the music skill
(``pricing.per_unit.credits``); a test keeps the two equal. Composed videos
with background music (``backend/apps/videos/tasks/generate_billing.py``)
charge this price per track.
"""

MUSIC_TRACK_CREDITS = 120
