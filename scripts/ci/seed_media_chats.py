#!/usr/bin/env python3
"""
scripts/ci/seed_media_chats.py

Seeds the media test account with realistic chats across different categories
for OG image / media generation screenshots.

Must be run inside the API Docker container:
    docker exec api python /app/scripts/ci/seed_media_chats.py

The script is idempotent — it checks for existing chats before creating new ones.
Uses mock markers to avoid LLM costs (backend intercepts <<<TEST_MOCK:...>>> markers
and returns cached fixture responses).

Prerequisites:
    - Media test account must exist (create with create_test_accounts.py --start 20 --end 20)
    - Set MEDIA_ACCOUNT_EMAIL env var or defaults to testacct20@test.openmates.org

Architecture: docs/media-generation.md
"""

import asyncio
import base64
import hashlib
import os
import sys

# Chat scenarios to seed — each creates one chat with a user message + assistant response.
# These are chosen to showcase the app's breadth across different categories.
MEDIA_CHATS = [
    {
        "title": "Cuttlefish Colors",
        "category": "general_knowledge",
        "user_message": "How do cuttlefish change color so quickly?",
        "assistant_message": (
            "Cuttlefish use specialized cells called **chromatophores** in their skin. "
            "Each chromatophore contains a sac of pigment surrounded by muscles. When the "
            "muscles contract, the pigment spreads out and the color becomes visible. When "
            "they relax, the pigment concentrates into a tiny point and the color disappears.\n\n"
            "They can change in about **200 milliseconds** — faster than a blink! They also "
            "have iridophores (reflective cells) and leucophores (white scattering cells) "
            "that add shimmer and brightness."
        ),
    },
    {
        "title": "React Hooks Guide",
        "category": "software_development",
        "user_message": "Explain useEffect cleanup functions",
        "assistant_message": (
            "The cleanup function in `useEffect` runs **before the effect re-runs** and "
            "**when the component unmounts**. It's essential for preventing memory leaks:\n\n"
            "```javascript\nuseEffect(() => {\n"
            "  const timer = setInterval(() => tick(), 1000);\n"
            "  return () => clearInterval(timer); // cleanup\n"
            "}, []);\n```\n\n"
            "Common use cases: clearing timers, unsubscribing from events, cancelling API requests."
        ),
    },
    {
        "title": "Pasta Carbonara",
        "category": "cooking_food",
        "user_message": "What's the traditional carbonara recipe?",
        "assistant_message": (
            "Traditional Roman carbonara uses just **5 ingredients**:\n\n"
            "1. **Guanciale** (cured pork cheek) — never bacon\n"
            "2. **Pecorino Romano** — sharp, salty sheep's milk cheese\n"
            "3. **Eggs** — whole eggs + extra yolks for richness\n"
            "4. **Black pepper** — freshly cracked, generously\n"
            "5. **Pasta** — rigatoni or spaghetti\n\n"
            "The key technique: toss hot pasta with the egg-cheese mixture **off the heat** "
            "to create a creamy sauce without scrambling the eggs."
        ),
    },
    {
        "title": "Morning Routine",
        "category": "life_coach_psychology",
        "user_message": "Help me build a better morning routine",
        "assistant_message": (
            "A solid morning routine has **3 pillars**: body, mind, and intention.\n\n"
            "**Body** (first 15 min):\n"
            "- Hydrate immediately — glass of water before anything else\n"
            "- Light movement: stretching, a short walk, or 5 min yoga\n\n"
            "**Mind** (next 10 min):\n"
            "- Journaling or gratitude practice (3 things you're grateful for)\n"
            "- Avoid phone/email for the first 30 minutes\n\n"
            "**Intention** (5 min):\n"
            "- Identify your **one priority** for the day\n"
            "- Visualize completing it successfully"
        ),
    },
    {
        "title": "Market Analysis",
        "category": "finance",
        "user_message": "How do I read a stock's P/E ratio?",
        "assistant_message": (
            "The **P/E ratio** (Price-to-Earnings) tells you how much investors pay per "
            "dollar of earnings:\n\n"
            "**P/E = Stock Price / Earnings Per Share**\n\n"
            "- **Low P/E (< 15)**: May be undervalued, or growth is slowing\n"
            "- **High P/E (> 25)**: Investors expect strong future growth\n"
            "- **Negative P/E**: Company is losing money\n\n"
            "Always compare P/E within the **same industry** — tech companies normally "
            "have higher P/E ratios than utilities."
        ),
    },
    {
        "title": "Movie Night",
        "category": "movies_tv",
        "user_message": "Recommend a thought-provoking sci-fi film",
        "assistant_message": (
            "**Arrival** (2016) — directed by Denis Villeneuve.\n\n"
            "A linguist is recruited to communicate with aliens who've landed on Earth. "
            "Instead of the usual action-heavy alien invasion, it's a deeply cerebral film "
            "about **language, time, and choice**.\n\n"
            "What makes it special:\n"
            "- Based on Ted Chiang's short story *Story of Your Life*\n"
            "- The Sapir-Whorf hypothesis is central to the plot\n"
            "- The twist recontextualizes the entire film\n"
            "- Amy Adams delivers a career-best performance"
        ),
    },
]


async def get_user_id(email: str) -> str | None:
    """Look up a user by email hash."""
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.cache import CacheService

    hashed_email = base64.b64encode(
        hashlib.sha256(email.lower().strip().encode("utf-8")).digest()
    ).decode("utf-8")

    cache = CacheService()
    ds = DirectusService(cache_service=cache)

    user = await ds.get_user_by_email_hash(hashed_email)
    return user.get("id") if user else None


async def main():
    email = os.environ.get("MEDIA_ACCOUNT_EMAIL", "testacct20@test.openmates.org")
    print(f"Seeding media chats for: {email}", file=sys.stderr)

    user_id = await get_user_id(email)
    if not user_id:
        print(f"ERROR: Media account not found: {email}", file=sys.stderr)
        print(
            "Create it first: docker exec api python /app/scripts/ci/create_test_accounts.py --start 20 --end 20",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Found user: {user_id}", file=sys.stderr)
    print(f"Would seed {len(MEDIA_CHATS)} chats:", file=sys.stderr)
    for chat in MEDIA_CHATS:
        print(f"  - {chat['title']} ({chat['category']})", file=sys.stderr)

    # TODO: Implement chat creation via the API once the media test account is set up.
    # The actual implementation depends on:
    # 1. Whether we use the WebSocket chat API or direct DB insertion
    # 2. How to handle encryption (chats are E2E encrypted, need the user's master key)
    # 3. Whether to use mock markers for the assistant responses
    #
    # For now, this script documents the intended chat content and validates
    # the account exists. The chats can be created manually via the app UI
    # by logging into the media test account.
    print(
        "\nNote: Automatic chat creation is not yet implemented.",
        file=sys.stderr,
    )
    print(
        "Log into the media account and create these chats manually for now.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
