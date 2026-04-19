# backend/apps/events/providers/__init__.py
# Events app providers package.
#
# Active providers:
#   - meetup:              Meetup.com event search via internal GraphQL API
#   - luma:                Luma.com event discovery via internal REST API (78 featured cities)
#   - google_events:       Google Events search via SerpAPI (aggregates multiple ticketing platforms)
#   - berlin_philharmonic: Berlin Philharmonic calendar (Typesense JSON API, Berlin-only)
#
# Inactive providers (in code but not wired into search_skill.py):
#   - classictic:  Concert listings (Berlin-focused, HTML scraper)
#   - bachtrack:   Concert listings (HTML scraper)
#
# Future providers (research phase):
#   - eventbrite:       API search removed in 2020 — investigating web scraping viability
#   - resident_advisor: RA blocked by 403 — needs headless browser or undocumented API
#   - siegessaeule:     Berlin LGBTQ+ events — investigating scraping viability
