# backend/apps/events/providers/__init__.py
# Events app providers package.
#
# Current providers:
#   - meetup: Meetup.com event search via internal GraphQL API
#
# Future providers (documented, not yet implemented):
#   - luma: Luma event discovery (lu.ma/<city> page scraping, no keyword search)
#   - eventbrite: Eventbrite REST API v3 (requires free API key)
#   - resident_advisor: RA blocked by 403 — needs headless browser or undocumented API
