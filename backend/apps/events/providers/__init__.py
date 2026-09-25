# backend/apps/events/providers/__init__.py
# Events app providers package.
#
# Active providers:
#   - meetup:              Meetup.com event search via internal GraphQL API
#   - luma:                Luma.com event discovery via internal REST API (78 featured cities)
#   - eventbrite:          Eventbrite web API search with event-page descriptions
#   - resident_advisor:    Resident Advisor electronic music and club events
#   - siegessaeule:        Berlin LGBTQ+ events
#   - berlin_philharmonic: Berlin Philharmonic calendar (Typesense JSON API, Berlin-only)
#   - pretalx:             Official conference schedules (GPN/Congress) via C3VOC JSON exports
#
# Inactive providers (in code but not wired into search_skill.py):
#   - classictic:  Concert listings (Berlin-focused, HTML scraper)
#   - bachtrack:   Concert listings (HTML scraper)
#
