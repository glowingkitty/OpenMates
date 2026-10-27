/** Presentation copy and timing copied from origin/main d72195d380 landing stories.
 * Sources: ui/i18n/sources/guest_onboarding.yml, chat/main.yml, mates.yml,
 * app_settings_memories/travel.yml and landing/*Timeline(s).ts.
 * These are recorded examples; no visitor data or inference is used. */
export const featureAnimationCopy = {
  "en": {
    "actionable_event_user_message": "Find music meetups in Amsterdam",
    "actionable_event_assistant_message": "Of course, here you go:",
    "actionable_event_title": "Amsterdam Music Gathering",
    "actionable_event_open_provider": "Open on event website",
    "actionable_event_venue": "A gathering by the canal",
    "actionable_event_in_person": "In person",
    "actionable_event_rsvps": "RSVPs",
    "privacy_saved_data": "Only your devices can decrypt all your data.",
    "privacy_pii": "Personal details are replaced, before the AI sees them.",
    "privacy_email_request": "Prepare an email to",
    "privacy_email_response": "Ok, preparing an email to",
    "privacy_trip_request": "Recommended places for my next trip?",
    "privacy_memory_result": "Personalized responses. But only when you want them.",
    "privacy_originals": "Only you can view the originals.",
    "permissionTitle": "Permissions",
    "permissionQuestion": "Include these memories in this chat, for a more personalized response?",
    "includeSelected": "Include selected",
    "rejectAll": "Reject all",
    "entries": "entries",
    "generalKnowledge": "George",
    "businessDevelopment": "Burton",
    "trips": "Trips"
  },
  "de": {
    "actionable_event_user_message": "Finde Musik-Meetups in Amsterdam",
    "actionable_event_assistant_message": "Natürlich, hier bitte:",
    "actionable_event_title": "Amsterdam Musik-Gathering",
    "actionable_event_open_provider": "Auf event website öffnen",
    "actionable_event_venue": "Ein Treffen am Kanal",
    "actionable_event_in_person": "Vor Ort",
    "actionable_event_rsvps": "Zusagen",
    "privacy_saved_data": "Nur deine Geräte können alle deine Daten entschlüsseln.",
    "privacy_pii": "Persönliche Angaben werden ersetzt, bevor die KI sie sieht.",
    "privacy_email_request": "Bereite eine E-Mail vor an",
    "privacy_email_response": "Ok, ich bereite eine E-Mail vor an",
    "privacy_trip_request": "Empfohlene Orte für meine nächste Reise?",
    "privacy_memory_result": "Personalisierte Antworten. Aber nur, wenn du sie möchtest.",
    "privacy_originals": "Nur du kannst die Originale sehen.",
    "permissionTitle": "Berechtigungen",
    "permissionQuestion": "Diese Erinnerungen in diesen Chat einbeziehen, für eine persönlichere Antwort?",
    "includeSelected": "Ausgewählte einbeziehen",
    "rejectAll": "Alle ablehnen",
    "entries": "Einträge",
    "generalKnowledge": "Albert",
    "businessDevelopment": "Gerd",
    "trips": "Reisen"
  }
} as const;

export const actionableStages = [
  { id: "user-request", durationMs: 1800 },
  { id: "assistant-response", durationMs: 1800 },
  { id: "event-preview", durationMs: 2700 },
  { id: "provider-cta", durationMs: 2200 },
] as const;

export const privacyStages = [
  { id: "saved-data-copy", durationMs: 1600 },
  { id: "encryption-lock", durationMs: 3000 },
  { id: "pii-copy", durationMs: 1600 },
  { id: "pii-detection", durationMs: 2400 },
  { id: "originals-copy", durationMs: 1600 },
  { id: "pii-reveal", durationMs: 2400 },
  { id: "personalized-copy", durationMs: 1600 },
  { id: "trip-request", durationMs: 1800 },
  { id: "memory-permission", durationMs: 4000 },
] as const;
