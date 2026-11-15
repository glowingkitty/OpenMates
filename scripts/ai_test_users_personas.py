"""Synthetic personas for the AI test-user trial (`scripts/ai_test_users.py`).

Every persona is fictional. Goals are realistic tasks a person would bring to
OpenMates and together cover chats and follow-ups, apps and skills (travel,
weather, code, recipes, jobs, maps, stays, events, slides), focus modes,
settings and privacy controls, embeds and fullscreen views, a German UI and
answers, voice input, phone and laptop sizes, and edge cases (very long
input, emoji, interrupting a streaming answer, an empty send, quick
follow-ups). Phones and tablets use Android Chrome user agents because the
sandbox browser is Chromium; an iPhone user agent on Chromium would invent
engine bugs that real users never see.
"""

from __future__ import annotations

ANDROID_PHONE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36"
)
ANDROID_TABLET_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DESKTOP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PHONE = {"width": 412, "height": 915, "scale": 2, "mobile": True, "touch": True, "user_agent": ANDROID_PHONE_UA}
SMALL_PHONE = {"width": 360, "height": 740, "scale": 2, "mobile": True, "touch": True, "user_agent": ANDROID_PHONE_UA}
TABLET = {"width": 800, "height": 1280, "scale": 1.5, "mobile": True, "touch": True, "user_agent": ANDROID_TABLET_UA}
LAPTOP = {"width": 1366, "height": 768, "scale": 1, "user_agent": DESKTOP_UA}
MACBOOK = {"width": 1440, "height": 900, "scale": 1, "user_agent": DESKTOP_UA}
DESKTOP = {"width": 1920, "height": 1080, "scale": 1, "user_agent": DESKTOP_UA}

PERSONAS: list[dict] = [
    {
        "id": "student",
        "name": "Lena (20), biology student",
        "description": "Second-year biology student preparing for an exam, writes quickly and casually, laptop in the library.",
        "language": "English",
        "device_label": "laptop 1366x768",
        "device": LAPTOP,
        "goals": [
            "Ask for a clear explanation of the light-dependent reactions of photosynthesis for an exam next week.",
            "Follow up: ask for it simpler, then for 5 quiz questions with answers hidden until asked.",
            "Pick a learning or study focus mode if the app offers one and see whether answers change.",
            "Open the chat list/sidebar, rename or find this chat again.",
        ],
    },
    {
        "id": "traveller",
        "name": "Sam (34), weekend traveller",
        "description": "Travels by train often, impatient, checks every result carefully before booking, uses a phone.",
        "language": "English",
        "device_label": "phone 412x915 (Android)",
        "device": PHONE,
        "goals": [
            "Find train or bus connections from Munich to Zurich for next Friday morning.",
            "Open a connection result/embed and its fullscreen view; check dates, times, prices and that every "
            "booking button belongs to the operator shown (a bus result must not link to a rail operator).",
            "Send a follow-up while the answer is still streaming: 'and what about returning Sunday evening?'",
        ],
    },
    {
        "id": "developer",
        "name": "Arjun (29), backend developer",
        "description": "Experienced Python developer, terse, pastes long code, expects precise answers, large monitor.",
        "language": "English",
        "device_label": "desktop 1920x1080",
        "device": DESKTOP,
        "goals": [
            "Paste a ~40-line Python asyncio snippet with a bug (gather without awaiting tasks, blocking time.sleep) "
            "and ask what is wrong.",
            "Ask the assistant to run a fixed version of the code if the app can execute code; inspect the code "
            "embed, copy button and fullscreen view.",
            "Ask a follow-up about a library version and check the answer does not invent APIs.",
        ],
    },
    {
        "id": "phone_voice",
        "name": "Gerda (67), non-technical phone user",
        "description": "Retired, not technical, uses a small phone, prefers speaking over typing, short sentences.",
        "language": "English",
        "device_label": "small phone 360x740 (Android)",
        "device": SMALL_PHONE,
        "voice_text": "What will the weather be like tomorrow in Hamburg? Do I need an umbrella?",
        "goals": [
            "Use the microphone/voice input button to ask about tomorrow's weather in Hamburg (the microphone plays "
            "a recorded question). If voice does not work, type the question instead.",
            "Read the answer and any weather card; check it is readable on a small screen and units make sense.",
            "Try to find how to make the text bigger or how to get help.",
        ],
    },
    {
        "id": "german",
        "name": "Jonas (41), German speaker",
        "description": "Lebt in Leipzig, schreibt nur Deutsch, erwartet deutsche Antworten und eine deutsche Oberfläche.",
        "language": "German",
        "locale": "de-DE",
        "device_label": "laptop 1440x900",
        "device": MACBOOK,
        "goals": [
            "Stelle in den Einstellungen die Sprache der Oberfläche auf Deutsch um (falls nicht schon Deutsch).",
            "Frage: 'Was kann ich am Wochenende in Leipzig mit Kindern unternehmen?' und prüfe, ob die Antwort, "
            "Datumsangaben und Karten/Embeds deutsch und korrekt formatiert sind.",
            "Stelle eine Rückfrage zu einem der Vorschläge (Öffnungszeiten, Preis).",
        ],
    },
    {
        "id": "cook",
        "name": "Maya (38), home cook",
        "description": "Cooks for a family of six, uses a tablet propped up in the kitchen, practical and detailed.",
        "language": "English",
        "device_label": "tablet 800x1280 (Android)",
        "device": TABLET,
        "goals": [
            "Ask for a vegetarian lasagne recipe and open any recipe result or embed.",
            "Ask to scale it to 6 people and give nutrition per portion; check numbers and units are plausible.",
            "Ask for a shopping list grouped by supermarket section. Include an emoji or two in your message 🍅🧀.",
        ],
    },
    {
        "id": "job_seeker",
        "name": "Tomás (26), job seeker",
        "description": "Recent graduate looking for a junior UX designer job in Berlin, a bit anxious, laptop.",
        "language": "English",
        "device_label": "laptop 1366x768",
        "device": LAPTOP,
        "goals": [
            "Search for junior UX designer jobs in Berlin and open job results; check titles, companies, dates and "
            "links match each other.",
            "Ask for a short cover letter for one of the found jobs.",
            "Try pressing send with an empty message, then send a very long message (a full CV pasted, ~300 words).",
        ],
    },
    {
        "id": "trip_planner",
        "name": "Aisha (31), planning a trip",
        "description": "Plans a 3-day weekend in Lisbon with a friend, compares options, phone on the commute.",
        "language": "English",
        "device_label": "phone 412x915 (Android)",
        "device": PHONE,
        "goals": [
            "Ask for a 3-day Lisbon itinerary for the weekend after next, with places on a map if possible.",
            "Ask for affordable places to stay and events happening that weekend; open the results and their details.",
            "Check that dates shown match the weekend asked for and that prices have currencies.",
        ],
    },
    {
        "id": "business_owner",
        "name": "Petra (52), small business owner",
        "description": "Runs a bakery with 8 employees, wants practical help fast, not into tech jargon, laptop.",
        "language": "English",
        "device_label": "laptop 1440x900",
        "device": MACBOOK,
        "goals": [
            "Ask for a polite payment-reminder email to a catering customer whose invoice is 30 days overdue.",
            "Ask for a short 5-slide presentation for staff about new opening hours (use a slides or presentation "
            "feature if the app has one) and open it.",
            "Ask what it costs to use the app (credits/pricing) and see if the answer matches what settings show.",
        ],
    },
    {
        "id": "privacy",
        "name": "Ruben (45), privacy-minded user",
        "description": "Cautious about data, reads settings carefully before trusting an app, phone.",
        "language": "English",
        "device_label": "phone 412x915 (Android)",
        "device": PHONE,
        "goals": [
            "Open the settings and find privacy, memory and data controls; check texts are understandable and complete.",
            "Start an incognito/private chat if the app offers it, ask 'What do you remember about me?', then check "
            "whether that chat appears in the chat list afterwards.",
            "Delete one of your own chats and confirm it is gone.",
        ],
    },
]


def select(ids: str) -> list[dict]:
    if ids == "all":
        return PERSONAS
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    known = {p["id"]: p for p in PERSONAS}
    missing = [i for i in wanted if i not in known]
    if missing:
        raise SystemExit(f"unknown personas: {', '.join(missing)}")
    return [known[i] for i in wanted]
