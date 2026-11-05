/** Presentation copy and timing copied from origin/main d72195d380 landing stories.
 * Sources: ui/i18n/sources/guest_onboarding.yml, chat/main.yml, mates.yml,
 * app_settings_memories/travel.yml and landing/*Timeline(s).ts.
 * These are recorded examples; no visitor data or inference is used. */
export const featureAnimationCopy = {
  "en": {
    "actionable_event_user_message": "Create an event card: FOSDEM 2027, 30–31 January, ULB Solbosch campus in Brussels.",
    "actionable_event_assistant_message": "Here is an event card from your supplied details.",
    "actionable_event_venue": "ULB Solbosch campus, Brussels",
    "actionable_event_illustration": "Illustrative interaction · supplied details",
    "actionable_event_description": "A two-day free and open-source software conference.",
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
    "actionable_event_user_message": "Erstelle eine Event-Karte: FOSDEM 2027, 30.–31. Januar, ULB-Campus Solbosch in Brüssel.",
    "actionable_event_assistant_message": "Hier ist eine Event-Karte aus deinen Angaben.",
    "actionable_event_venue": "ULB-Campus Solbosch, Brüssel",
    "actionable_event_illustration": "Beispielinteraktion · bereitgestellte Angaben",
    "actionable_event_description": "Eine zweitägige Konferenz für freie und quelloffene Software.",
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
  { id: "event-preview", durationMs: 3600 },
  { id: "event-details", durationMs: 6000 },
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

/** Fixed supplied facts, not a real chat transcript or a live discovery claim.
 * Approved source: docs/plans/assistant-authored-result-embeds/fosdem-sources.md.
 * Date-only values deliberately carry no invented opening or closing hours. */
export const landingAuthoredEvent = {
  title: 'FOSDEM 2027',
  dateStart: '2027-01-30',
  calendarEndExclusive: '2027-02-01',
  sourceUrl: 'https://fosdem.org/2027/news/fosdem-2027-dates/',
} as const;
