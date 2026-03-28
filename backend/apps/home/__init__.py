# backend/apps/home/__init__.py
# Home app — German apartment and housing search.
#
# Searches ImmoScout24, Kleinanzeigen, and WG-Gesucht for apartments,
# houses, and WG rooms across Germany. All three providers use public
# endpoints (no API keys required). Results are merged, deduplicated,
# and returned as parent search embeds with child listing embeds.
