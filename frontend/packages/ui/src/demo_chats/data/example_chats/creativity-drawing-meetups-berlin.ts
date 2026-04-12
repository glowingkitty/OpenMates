// frontend/packages/ui/src/demo_chats/data/example_chats/creativity-drawing-meetups-berlin.ts
//
// Example chat: Creativity Drawing Meetups Berlin
// Extracted from shared chat 194d9fcc-8d9a-4bd7-a054-4016ade975fd
//
// A real conversation showcasing the events search skill,
// finding drawing and creativity meetups happening in Berlin next week.

import type { ExampleChat } from "../../types";

export const creativityDrawingMeetupsBerlinChat: ExampleChat = {
  chat_id: "example-creativity-drawing-meetups-berlin",
  slug: "creativity-drawing-meetups-berlin",
  title: "example_chats.creativity_drawing_meetups_berlin.title",
  summary: "example_chats.creativity_drawing_meetups_berlin.summary",
  icon: "pencil",
  category: "general_knowledge",
  keywords: [
    "drawing meetups Berlin", "creativity workshops Berlin", "art meetups",
    "life drawing Berlin", "watercolor workshop", "open draw",
    "collaborative drawing", "linocut Berlin", "art sketching",
    "creative events Berlin", "painting meetups", "Prenzlauer Berg art"
  ],
  follow_up_suggestions: [
    "example_chats.creativity_drawing_meetups_berlin.follow_up_1",
    "example_chats.creativity_drawing_meetups_berlin.follow_up_2",
    "example_chats.creativity_drawing_meetups_berlin.follow_up_3",
    "example_chats.creativity_drawing_meetups_berlin.follow_up_4",
    "example_chats.creativity_drawing_meetups_berlin.follow_up_5",
    "example_chats.creativity_drawing_meetups_berlin.follow_up_6",
  ],
  messages: [
    {
      id: "16ade975fd-cec9997e-7b3f-4fdc-ae9e-8d94db723959",
      role: "user",
      content: "example_chats.creativity_drawing_meetups_berlin.user_message_1",
      created_at: 1776000845,
      category: "general_knowledge",
    },
    {
      id: "8615b9ad-b4bc-45e4-8501-5e50d20861f1",
      role: "assistant",
      content: "example_chats.creativity_drawing_meetups_berlin.assistant_message_1",
      created_at: 1776000851,
      category: "general_knowledge",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "72502268-d788-4a82-b63c-6c2f38f1e028",
      type: "event",
      content: `type: event_result
id: "313860302"
provider: meetup
title: Open Draw
description: "Kommt am 2. Montagabend im Monat ins Offene Wohnzimmer zum Open Draw!\\n\\nRaucht Euch auch manchmal der Kopf von zu viel PC-Arbeit? Der Asphalt der Stadt ist heute wieder viel zu grau? Ihr würdet am liebsten mal wieder wild auf einem Blatt Papier rumklecksen oder gedankenverlorene Linien zeichnen?\\n\\nHöchste Zeit zur Tat zu schreiten!\\nWir wollen in entspannter Atmosphäre die kreativen Zellen auf Volldampf fahren und uns der Inspiration überlassen. Mit Musik im Hintergrund sowie Wein, Tee und Snacks im Repertoire wird dann gekleckst, gemalt, gezeichnet, geklebt, geredet und gelacht. Das Ganze kann sehr ambitioniert stattfinden, aber genauso zum Hirn-abschalten dienen. Austausch, Bilderswapping und gegenseitige Tipps/Kritik sind sehr willkommen.\\nMaterial stellen wir (Kreide, Bleistift, Wasserfarbe, Acrylfarbe, Pastellstifte, Kohle, Papierbögen, Spiegel, Postkarten, Zeichenbücher, Illustrierte).\\nSujet kann alles sein: Der/die Tischnächste, der letzte Traum, oder der Feldhase Dürers. Technik auch: Von (Selbst)portrait über Stilleben bis zur Comiczeichnung soll alles abgedeckt werden.\\nWir bieten jeden 2. Montag im Monat offene Treffen zum kreativen Arbeiten sowie gelegentlich technik- und themenbasierte Workshops an.\\nWie immer wird um eine Spende für Raummiete/Material von 5-10€ gebeten.\\n\\nAnmeldung: Katharinav.runnen@gmx.de"
url: "https://www.meetup.com/offenes-wohnzimmer-berlin/events/313860302/"
date_start: "2026-04-13T18:00:00+02:00"
date_end: "2026-04-13T21:00:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Offenes Wohnzimmer
venue_address: Waldenserstraße 13
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.529018
venue_lon: 13.332935
organizer_id: "33121633"
organizer_name: "Offenes Wohnzimmer: Moabit Nachbarschaft"
organizer_slug: offenes-wohnzimmer-berlin
rsvp_count: 2
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/b/6/6/a/highres_499306698.jpeg"
hash: 785cdef5b7347114
embed_ref: open-draw-djE
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "f72e1260-99ac-43cd-a236-f05d5c6307b8",
      type: "event",
      content: `type: event_result
id: "313944512"
provider: meetup
title: "Collaborative Drawing & Printing group, Rhinower Str 10, 10437. Just try it!!!"
description: "Communicative, collaborative and creative drawing sessions. Participants draw a central still-life that the group can create themselves until the music track finishes and then pass it to the person on their left. The drawings change hands 3 to 5 times and the end results are always inspiring. After the collaborative warm-up participants can work individually on printing techniques, Mono -printing, tetra-pack or gelli. -printing. Feel free to try out a process that you are unfamiliar with. There will always be somebody to offer advice if necessary Bring A4 paper, and favourite materials, pencils & brushes. You can also use some studio materials in exchange for a small contribution. A fun but informative approach with consistently creative results!"
url: "https://www.meetup.com/ww-alexinegood-de/events/313944512/"
date_start: "2026-04-14T18:00:00+02:00"
date_end: "2026-04-14T19:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Studio Good
venue_address: "Rhinowerstr.10, Rhinowerstr.10"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.548176
venue_lon: 13.409631
organizer_id: "36285637"
organizer_name: Rhinower 10 Studio/ Art & Language
organizer_slug: ww-alexinegood-de
rsvp_count: 1
is_paid: true
fee_amount: 20.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/4/e/3/6/highres_514820022.jpeg"
hash: 2d7b2a880a7b080a
embed_ref: collaborative-drawing-printing-aH1
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "39a44531-dcbc-4ec3-a5dd-d1f251f0247b",
      type: "event",
      content: `type: event_result
id: "2411067"
provider: resident_advisor
title: Klubkneipe x Tuesday Ritual
description: "Lineup: Martinii, DJoy, Khmgnff\\nGenres: House\\nTuesday Ritual at Prisma\\nhosted by Caos Collective\\n\\nThis week we invite you to a Macramé Workshop with Napa Design — a hands-on crafting session focused on slowing down, creating and connecting.\\n\\nAccompanied by housy, groovy sounds by DJOY, Najjka, Martinii & KHMGNFF, setting the tone for a soft and creative evening.\\n\\nCome by to craft, listen or simply spend time together.\\n\\n6 PM – 2 AM\\n"
url: "https://ra.co/events/2411067"
date_start: "2026-04-14T18:00:00.000"
date_end: "2026-04-15T02:00:00.000"
timezone: null
event_type: PHYSICAL
venue_name: Prisma
venue_address: "Brückenstraße 1, 10179 Berlin"
venue_city: Berlin
venue_state: null
venue_country: null
venue_lat: 52.51
venue_lon: 13.42
organizer: null
rsvp_count: 2
is_paid: true
fee_amount: "0"
fee_currency: EUR
image_url: "https://images.ra.co/16363668ae819bc96866a8d130f1a5640075b6a2.png"
artists: Martinii|DJoy|Khmgnff
genres: House
minimum_age: 18
is_festival: false
hash: b247e26533241ffb
embed_ref: klubkneipe-x-tuesday-Hmf
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "28197f57-550b-4daa-8503-14fd9d31f5dc",
      type: "event",
      content: `type: event_result
id: "313945633"
provider: meetup
title: InnerGrowth Workshop
description: "Du möchtest dich **persönlich weiterentwickeln**?\\nDu bist offen für **spirituelle Arbeit**?\\nDann ist der InnerGrowth Workshop perfekt für dich!\\n\\n🌟 Was dich erwartet:\\n\\n* Übungen für mehr **positive Energie**, **mentale Klarheit**\\n* **Transformation stagnierender Energien**\\n* **BONUS**: Energetische Unterstützung durch eine spezielle Frequenzmethode zur Vertiefung der Wirkung der Übungen!\\n\\n✨ Neugierig geworden?\\nErlebe wie transformierend der InnerGrowth Workshop ist und **melde dich hier verbindlich an**: [https://form.jotform.com/260492716608058](https://form.jotform.com/260492716608058)\\n\\n***❗ Nach deiner verbindlichen Anmeldung erhältst du die genauen Treffpunkt-Details ❗***\\n\\n📌 **Wichtige Hinweise**\\n\\n* ***Verbindliche Anmeldung:***\\nVerbindliche Anmeldung über das Anmeldeformular hier: [https://form.jotform.com/260492716608058](https://form.jotform.com/260492716608058)\\n* ***Telegram-Gruppe:***\\nTritt gerne auch der Telegram-Gruppe „InnerGrowth Circle“ bei – zum Vernetzen und für eine einfache Event-Kommunikation: https://t.me/+pVtQhF3ykX01YmY6\\n* ***Kosten***:\\n22 Euro. Barzahlung vor Ort\\n* ***Ort***:\\nKalckreuthstraße, Berlin (Nähe U Nollendorfplatz)\\n\\n🔥 **Was bietet mir eine Teilnahme?**\\nDieser Workshop bietet dir spirituellen Support für deine persönliche Entwicklung. Du erhältst Werkzeuge und Impulse, die dich energetisch ausrichten, stärken und fokussieren – und wirst dabei zusätzlich von mir durch eine besondere energetische Unterstützung begleitet.\\n\\nGleichzeitig hast du die Gelegenheit, Gleichgesinnte kennen zu lernen, dich auszutauschen und deine persönliche Reise in einem unterstützenden Umfeld zu vertiefen.\\n\\nIch freu mich auf dich!\\n\\n❗*Hinweis: Die im Workshop vermittelten Inhalte stellen keine medizinische, heilkundliche oder psychotherapeutische Behandlung dar. Es werden keine Diagnosen gestellt und keine Heilversprechen abgegeben. Die Teilnahme ersetzt keinen Arzt- oder Heilpraktikerbesuch.*"
url: "https://www.meetup.com/lebendige-spiritualitat-entfalte-dein-wahres-selbst/events/313945633/"
date_start: "2026-04-14T18:30:00+02:00"
date_end: "2026-04-14T20:00:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: InnerGrowth Workshop
venue_address: Kalckreuthstraße
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.499207
venue_lon: 13.348126
organizer_id: "38233341"
organizer_name: Lebendige Spiritualität – Entfalte dein wahres Selbst!
organizer_slug: lebendige-spiritualitat-entfalte-dein-wahres-selbst
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/4/d/2/6/highres_533119750.jpeg"
hash: 4f12dffa4bc8ad9a
embed_ref: innergrowth-workshop-dTm
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "34d41552-fa80-4626-8c73-8dfedfa18d38",
      type: "event",
      content: `type: event_result
id: "314177993"
provider: meetup
title: "Neurodivergent Creative Tuesdays "
description: "* **NEW IG ACCOUNT: [@neurocrafting.berlin](https://www.instagram.com/neurocrafting.berlin?utm_source=ig_web_button_share_sheet&igsh=ZDNlZDc0MzIxNw==) (ﾉ◕ヮ◕)ﾉ\\\\*:･ﾟ✧**\\n\\nCalling all neurodivergent individuals! Are you tired of starting hobbies that you never seem to finish? Join us for an evening of guilt-free creativity where there is absolutely no pressure to complete anything.\\n\\nThis event is designed to be a safe space where you can freely express your creativity without fear of judgment or criticism.\\n\\nWe will have a variety of crafting supplies available including paint, yarn, crochet needles, beads, coloring books, origami paper, markers... However, feel free to bring your own supplies or current projects if you'd like to work on something specific.\\n\\n**There is a donation of a minimum of 4-5 euros to cover the materials and space.** In case you wish to pay via paypal: neurocrafting.berlin@gmail.com"
url: "https://www.meetup.com/neurodivergent-creative-club/events/314177993/"
date_start: "2026-04-14T20:00:00+02:00"
date_end: "2026-04-14T22:00:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Grünberger Str. 16
venue_address: Grünberger Str. 16
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.512753
venue_lon: 13.449764
organizer_id: "37501413"
organizer_name: Neurodivergent Creative Club
organizer_slug: neurodivergent-creative-club
rsvp_count: 15
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/3/c/8/6/highres_519015494.jpeg"
hash: ee3c0b5befa396dd
embed_ref: neurodivergent-creative-tuesdays-RQX
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "a93af071-ac34-4161-af81-68b97f8da3c2",
      type: "event",
      content: `type: event_result
id: "313959758"
provider: meetup
title: "Creatives Co-Working: Wonderful Wednesdays (Online)"
description: "Join us on Wednesdays for some creative work. Whether it's a creative project, your taxes or your work for the week.\\n\\nLet's start the week strong!\\n\\nWHO: We're creative freelancers, artists, writers, students, job hunters academics and self-employed people. New people are always welcome!\\n\\nWHERE: JOIN ONLINE\\n\\nFORMAT:\\n15:00 - Introductions, sharing what we're working on this session.\\n\\nWednesdays we'll be using the [Pomodoro Method](https://en.wikipedia.org/wiki/Pomodoro_Technique), which is marked by 25 minute sprints and 5 or 15 minute breaks.\\n\\n17:00 Finish, reflect, celebrate, hang out.\\n\\nEveryone who likes can also continue working together for some additional motivating coop and stay in the video meeting.\\n\\n* If you are late to join the meetup that's okay, just get started with your work and we can chat in the breaks.\\n\\nThese events are free, but if you feel inclined to 'buy a coffee' (donate a small amount) to help cover the Meetup subscription costs, that would be most appreciated."
url: "https://www.meetup.com/artists-in-berlin/events/313959758/"
date_start: "2026-04-15T15:00:00+02:00"
date_end: "2026-04-15T17:00:00+02:00"
timezone: Europe/Berlin
event_type: ONLINE
venue_name: Online event
venue_address: ""
venue_city: ""
venue_state: ""
venue_country: ""
venue_lat: -8.521147
venue_lon: 179.1962
organizer_id: "31531526"
organizer_name: Artists and Creatives Co-working in Berlin
organizer_slug: Artists-in-Berlin
rsvp_count: 5
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/7/7/4/4/highres_518970532.jpeg"
hash: 219a0b40929646fc
embed_ref: creatives-co-working-kZe
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "1bf73b29-7328-4783-8ad2-e13dda0b726a",
      type: "event",
      content: `type: event_result
id: "2402015"
provider: resident_advisor
title: PUSH PLAY KINKY SERIES//THE APPLE EDITION
description: "Genres: Techno, Disco\\nThe Apple Edition is here! welcoming shots and free apples all night :D\\n         THE HYPE IS REAL!!!!!\\n\\nThis is more than just a party—it’s the beginning of a community dedicated to exploring kink, connection, and creativity in an atmosphere of trust and mutual respect.\\n\\n+What to Expect\\n\\n· An immersive, playfully curated environment designed to awaken the senses\\n· Music that moves between sensual, deep, and electric\\n· Spaces for interaction, play, and relaxation, every event would have a theme fruit, this fruit will also be served free for the guests throughout the party. as well as welcoming shot at the door.\\n· A welcoming, diverse crowd of curious minds and open hearts\\n\\n+Our Foundation: Respect, Consent, and Culture\\n\\nTo ensure a safe and enriching experience for everyone, our events are built on clear principles. By attending, you agree to uphold the following:\\n\\n1. Consent is Non-Negotiable\\n· Always ask before touching, joining, or interacting—no exceptions.\\n· A “no” or even a “not sure” is a complete answer. Respect it immediately and gracefully.\\n· Check in with your partners and those around you. Consent is ongoing and can be withdrawn at any time.\\n\\n2. Respect the Space and the Community\\n· This is a sanctuary for exploration, not a spectacle. Photography is strictly prohibited.\\n· Come as your most authentic self, and allow others to do the same. Judgment-free means exactly that.\\n· Honor the venue, and treat the space as you would a trusted friend’s home.\\n\\n3. Embrace the Culture, Don’t Appropriate It\\n· \\nKiNK\\n and BDSM have deep roots and histories. Engage with curiosity, not entitlement.\\n· If you’re new, welcome! Listen, learn, and participate with humility. If you’re experienced, share knowledge generously, not condescendingly.\\n· Symbols, attire, and practices often carry meaning. Respect their significance—ignorance is not an excuse.\\n\\n4. Confidentiality and Discretion\\n· What happens here stays here. Do not share names, stories, or identities outside this space...."
url: "https://ra.co/events/2402015"
date_start: "2026-04-15T23:00:00.000"
date_end: "2026-04-16T06:00:00.000"
timezone: null
event_type: PHYSICAL
venue_name: Mena Berlin
venue_address: "Skalitzer Straße 114 (Backyard), 10999 Berlin, Germany"
venue_city: Berlin
venue_state: null
venue_country: null
venue_lat: 52
venue_lon: 13
organizer_name: Push Play Erotics
organizer_slug: null
organizer_id: null
rsvp_count: 2
is_paid: true
fee_amount: "10"
fee_currency: EUR
image_url: "https://images.ra.co/79dbd8287b08b086bc52c3f329c8427c69153ede.jpg"
artists: null
genres: Techno|Disco
minimum_age: 19
is_festival: false
hash: 7b1033be2594f74a
embed_ref: push-play-kinky-HiW
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "357f3d06-816b-4c89-9b83-fc39d92a4f0d",
      type: "event",
      content: `type: event_result
id: evt-pe0rkhKRk5rW5es
provider: luma
title: "Handpicked Live: Real AI Starts at the Terminal"
description: "Important notes:\\nThis in-person workshop runs over two weeks: April 16th and 23rd from 18.00 to 21.00 (2 hours of learning and 1 hour to mingle and share the experience).\\nIf you have any questions regarding the scope or how the workshop will be run, email Phil: me@phil.is\\nWe will provide snacks (🍕) so you won't be hungry\\nThis is a great opportunity to ask your manager to use your learning and development budget - here is a template e-mail\\nIf you'd love to come, but have a scheduling conflict, let us know by choosing the free ticket type.\\nWhat is this?\\nForget the chat interface. The real power of AI tools like Claude Code and Codex lives in the terminal. And if a blinking cursor makes you want to close the window and walk away, you're leaving most of that power on the table.\\nMicrosoft's CEO Satya Nadella says agents will replace all software. The terminal is where those agents live. This workshop gets you there and prepares you for the agentic future.\\nWho is this for?\\nThis workshop is for founders, employees, freelancers, and creatives who've wanted to build something — a browser extension, a task manager, a productivity tool, or anything you want — but never had the technical background or time to figure it out.\\nNo technical experience needed. Beginners are especially welcome.\\nHow will it work?\\nOver two hands-on sessions, Phil and Igor will take you from \\"what even is a terminal?\\" to building your own working piece of software.\\nThe week between sessions is intentional. It gives you time to experiment on your own, get stuck, figure things out and then come back to session 2 with real questions and share the experience with others.\\nYou'll learn command-line basics, get set up with AI coding agents like Claude Code and Codex, and learn how to guide them so they actually build what you want.\\nSession 1 — Build your first piece of software: a browser extension, a Pomodoro timer, a task manager, or a plugin of your choice.\\nSession 2 — A recap of the latest AI developments,"
url: "https://lu.ma/real-AI-terminal"
date_start: "2026-04-16T16:00:00.000Z"
date_end: "2026-04-16T19:00:00.000Z"
timezone: Europe/Berlin
event_type: offline
venue_name: Mindspace Kurfürstendamm
venue_full_address: "Mindspace Kurfürstendamm, Uhlandstraße 32, 10719 Berlin, Germany"
venue_short_address: "Uhlandstraße 32, Berlin-Bezirk Charlottenburg-Wilmersdorf"
venue_city: Berlin
venue_state: Berlin
venue_country: Germany
venue_country_code: DE
venue_lat: 52.500418499999995
venue_lon: 13.3247811
organizer_name: Handpicked Berlin
organizer_avatar_url: "https://images.lumacdn.com/calendars/q8/c97b8a3b-9ca4-46ec-86d4-00fe45067ef2"
organizer_slug: handpicked
hosts[2]{name,avatar_url}:
  Igor Ranc,"https://images.lumacdn.com/avatars/f0/ea3d68dd-d2bb-441e-8236-3067558c04ae.jpg"
  Phil Bennett,"https://images.lumacdn.com/avatars/0m/7a0af3f5-6c12-4864-8379-3a8013a3c7ab.jpg"
rsvp_count: null
is_paid: false
cover_url: "https://images.lumacdn.com/event-covers/01/27a48c22-a2c9-4529-b030-f6b86a1d2c7d.jpg"
city: Berlin
country: Germany
image_url: "https://images.lumacdn.com/event-covers/01/27a48c22-a2c9-4529-b030-f6b86a1d2c7d.jpg"
hash: aa9b573529afa5d4
embed_ref: handpicked-live-real-67y
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "8aafebba-ad72-4526-be20-760d1e73f6e9",
      type: "event",
      content: `type: event_result
id: "314071039"
provider: meetup
title: Improv Thursdays 🎭
description: "Ready to break routine and try something new? Every Thursday evening, we turn a simple rehearsal room into a space for play, connection, and creativity. No scripts, no pressure—just two hours of pure improvisation.\\n Through theatre games, storytelling, and spontaneous scenes, you’ll discover how to: • Think faster and trust your instincts. • Collaborate with people you’ve just met. • Let go of self-judgment and enjoy the unexpected.\\n 💡 No acting background needed—if you can listen, laugh, and say “yes”, you’re ready.\\n Your Facilitator – Marianne\\n A theatre director and improvisation facilitator, Marianne has led workshops in Berlin, Düsseldorf, and London. Her approach is playful, inclusive, and focused on creating a supportive space where everyone can shine.\\n 📅 When & Where 🗓 Thursdays, 18:30–20:30 📍 Boxhagener Straße 18, 10245- 🔗 Sliding Scale Tickets – 5 € / 10 € / 15 €12 spots only – book in advance to secure your place.\\n 💬📲 Can't make it but you want to be part of the community? Here‘s the link: https://chat.whatsapp.com/EcNOFzscHnYBeUxUkNjsXP?mode=ems_copy_c\\n Come curious, leave inspired!\\n Tickets: https://www.eventbrite.com/e/improv-thursdays-tickets-1586525694059?aff=oddtdtcreator"
url: "https://www.meetup.com/improv-thursdays/events/314071039/"
date_start: "2026-04-16T18:30:00+02:00"
date_end: "2026-04-16T20:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Theatre Pool
venue_address: Boxhagener Strasse 18
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.513023
venue_lon: 13.455315
organizer_id: "38144780"
organizer_name: Improv Thursdays
organizer_slug: improv-thursdays
rsvp_count: 4
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/d/4/f/1/highres_529614513.jpeg"
hash: 838a22214bbc3ba3
embed_ref: improv-thursdays-zos
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "707ef95c-b5fb-4094-8757-f3c9a5943438",
      type: "event",
      content: `type: event_result
id: "313925797"
provider: meetup
title: "Creatives Co-Working: Motivating Mondays (Online)"
description: "Join us on Mondays for some creative work. Whether it's a creative project, your taxes or your work for the week.\\n\\nLet's start the week strong!\\n\\nWHO: We're creative freelancers, artists, writers, students, job hunters academics and self-employed people. New people are always welcome!\\n\\nWHERE: JOIN ONLINE\\n\\nFORMAT:\\n15:00 - Introductions, sharing what we're working on this session.\\n\\nMondays we'll be using the [Pomodoro Method](https://en.wikipedia.org/wiki/Pomodoro_Technique), which is marked by 25 minute sprints and 5 or 15 minute breaks.\\n\\n17:00 Finish, reflect, celebrate, hang out.\\n\\nEveryone who likes can also continue working together for some additional motivating coop and stay in the video meeting.\\n\\n* If you are late to join the meetup that's okay, just get started with your work and we can chat in the breaks.\\n\\nThese events are free, but if you feel inclined to 'buy a coffee' (donate a small amount) to help cover the Meetup subscription costs, that would be most appreciated. You can do so via this Ko-Fi link: https://ko-fi.com/creativelife"
url: "https://www.meetup.com/artists-in-berlin/events/313925797/"
date_start: "2026-04-13T15:00:00+02:00"
date_end: "2026-04-13T17:00:00+02:00"
timezone: Europe/Berlin
event_type: ONLINE
venue_name: Online event
venue_address: ""
venue_city: ""
venue_state: ""
venue_country: ""
venue_lat: -8.521147
venue_lon: 179.1962
organizer_id: "31531526"
organizer_name: Artists and Creatives Co-working in Berlin
organizer_slug: Artists-in-Berlin
rsvp_count: 2
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/8/3/b/9/highres_511473721.jpeg"
hash: 02359fa3dd0c2ae0
embed_ref: creatives-co-working-LpA
app_id: events
skill_id: search`,
      parent_embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      embed_ids: null,
    },
    {
      embed_id: "1a1bc73d-d492-4e4e-8c2d-d4045207a333",
      type: "event",
      content: `type: event_result
id: "313860302"
provider: meetup
title: Open Draw
description: "Kommt am 2. Montagabend im Monat ins Offene Wohnzimmer zum Open Draw!\\n\\nRaucht Euch auch manchmal der Kopf von zu viel PC-Arbeit? Der Asphalt der Stadt ist heute wieder viel zu grau? Ihr würdet am liebsten mal wieder wild auf einem Blatt Papier rumklecksen oder gedankenverlorene Linien zeichnen?\\n\\nHöchste Zeit zur Tat zu schreiten!\\nWir wollen in entspannter Atmosphäre die kreativen Zellen auf Volldampf fahren und uns der Inspiration überlassen. Mit Musik im Hintergrund sowie Wein, Tee und Snacks im Repertoire wird dann gekleckst, gemalt, gezeichnet, geklebt, geredet und gelacht. Das Ganze kann sehr ambitioniert stattfinden, aber genauso zum Hirn-abschalten dienen. Austausch, Bilderswapping und gegenseitige Tipps/Kritik sind sehr willkommen.\\nMaterial stellen wir (Kreide, Bleistift, Wasserfarbe, Acrylfarbe, Pastellstifte, Kohle, Papierbögen, Spiegel, Postkarten, Zeichenbücher, Illustrierte).\\nSujet kann alles sein: Der/die Tischnächste, der letzte Traum, oder der Feldhase Dürers. Technik auch: Von (Selbst)portrait über Stilleben bis zur Comiczeichnung soll alles abgedeckt werden.\\nWir bieten jeden 2. Montag im Monat offene Treffen zum kreativen Arbeiten sowie gelegentlich technik- und themenbasierte Workshops an.\\nWie immer wird um eine Spende für Raummiete/Material von 5-10€ gebeten.\\n\\nAnmeldung: Katharinav.runnen@gmx.de"
url: "https://www.meetup.com/offenes-wohnzimmer-berlin/events/313860302/"
date_start: "2026-04-13T18:00:00+02:00"
date_end: "2026-04-13T21:00:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Offenes Wohnzimmer
venue_address: Waldenserstraße 13
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.529018
venue_lon: 13.332935
organizer_id: "33121633"
organizer_name: "Offenes Wohnzimmer: Moabit Nachbarschaft"
organizer_slug: offenes-wohnzimmer-berlin
rsvp_count: 2
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/b/6/6/a/highres_499306698.jpeg"
hash: 785cdef5b7347114
embed_ref: open-draw-iPc
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "296b0b8b-74ad-467e-9c1f-d0d6f72b1b65",
      type: "event",
      content: `type: event_result
id: "313907649"
provider: meetup
title: "Watercolours for Beginners - Practise Group "
description: "If you’re just starting out with watercolours—maybe you’ve painted a bit at home or followed a tutorial or two, but still feel a little lost—I think you’re going to like this!\\n\\nFirst, we’ll practice **wet-on-wet, layering washes, colour mixing, transparency** and more. After this first part of the class, once you’ve discovered a few watercolour effects, you’ll have time to practise them by applying them to simple shapes (animals, plants, etc.) that I’ll provide. With the help of examples—and my guidance, of course—you’ll practise alongside other watercolour enthusiasts, supporting and learning from one another. Feel free to bring ideas and questions about things you'd like to paint :)\\n\\n**No previous experience needed**—just curiosity and a willingness to explore.\\n\\n###\\n\\n**Mondays 13 - 20 April** from 6:00 to 7:30 PM\\n**In Friedrichshain**, Berlin (exact address by e-mail)\\nJoin us for one or both classes, as you prefer. They are independent but complementary.\\n\\n**Price:**\\n\\n* 27€ x class / 50€ x 2 classes\\nPayment via PayPal / Bank transfer\\n\\n**Material:**\\nMaterial for watercolours is very specific. If you use poor-quality or non-professional material, you won't achieve the optimal results.\\n\\nPlease check this helpful guide:\\n[https://www.instagram.com/p/CKWdOx6FczD/](https://www.instagram.com/p/CKWdOx6FczD/)\\n\\n* I recommend bringing your own material so you can keep practising at home after the classes. If you don't want to buy it, I can also lend it to you for a small extra fee of 5€. Please let me know in advance.\\n\\n###\\n\\n**Booking by email only:**\\nEmail: **hola.berlinartclub@gmail.com**\\nYou’ll receive payment details and the exact address upon confirmation.\\n\\n🎟 **Spaces are limited—join us!**\\nRSVP here does not save you a spot.\\n\\nwww.lujancordaro.com\\n[@lujancordaro](www.instagram.com/lujancordaro)\\n[@berlin.art.club](www.instagram.com/berlin.art.club)"
url: "https://www.meetup.com/berlinartclub/events/313907649/"
date_start: "2026-04-13T18:00:00+02:00"
date_end: "2026-04-13T19:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Grünberger Straße
venue_address: Grünberger Str.
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.512035
venue_lon: 13.455164
organizer_id: "23034610"
organizer_name: Berlin Art Club
organizer_slug: berlinartclub
rsvp_count: 3
is_paid: true
fee_amount: 27.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/e/2/7/7/highres_533217975.jpeg"
hash: 249fba2c27f506fd
embed_ref: watercolours-for-beginners-WY8
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "a720fd63-e71f-452b-8ce2-680dc0554a9c",
      type: "event",
      content: `type: event_result
id: "313944512"
provider: meetup
title: "Collaborative Drawing & Printing group, Rhinower Str 10, 10437. Just try it!!!"
description: "Communicative, collaborative and creative drawing sessions. Participants draw a central still-life that the group can create themselves until the music track finishes and then pass it to the person on their left. The drawings change hands 3 to 5 times and the end results are always inspiring. After the collaborative warm-up participants can work individually on printing techniques, Mono -printing, tetra-pack or gelli. -printing. Feel free to try out a process that you are unfamiliar with. There will always be somebody to offer advice if necessary Bring A4 paper, and favourite materials, pencils & brushes. You can also use some studio materials in exchange for a small contribution. A fun but informative approach with consistently creative results!"
url: "https://www.meetup.com/ww-alexinegood-de/events/313944512/"
date_start: "2026-04-14T18:00:00+02:00"
date_end: "2026-04-14T19:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Studio Good
venue_address: "Rhinowerstr.10, Rhinowerstr.10"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.548176
venue_lon: 13.409631
organizer_id: "36285637"
organizer_name: Rhinower 10 Studio/ Art & Language
organizer_slug: ww-alexinegood-de
rsvp_count: 1
is_paid: true
fee_amount: 20.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/4/e/3/6/highres_514820022.jpeg"
hash: 2d7b2a880a7b080a
embed_ref: collaborative-drawing-printing-651
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "69309294-085d-4fa3-81e4-5271d45d5652",
      type: "event",
      content: `type: event_result
id: "313782414"
provider: meetup
title: Fantastic Anatomy Watercolour Workshop
description: "### **Fantastic Anatomy**\\n\\nIn this unique workshop, we will explore and celebrate the human body in all its beautiful complexity — and then let our imagination transform it.\\n\\nWhat does a sacrum look like? Could it become a butterfly?\\nHow do hands truly connect? Can we paint the magic of a gentle touch?\\nWhat lives in our hearts?\\n\\nTogether, we will observe the body with curiosity and appreciation, and then reimagine it through colour and fantasy. This workshop is an invitation to experience the body not only as anatomy, but as a living, poetic vessel that carries us through life.\\n\\nOver four classes, we will explore bones, muscles, and organs in a fresh and expressive way. Using watercolour techniques that embrace fluidity and transparency, we’ll experiment with water, stains, textures, and layering to create our own artistic vision of the body.\\n\\nJoin me in this colourful tribute to the extraordinary vessel we inhabit — where science meets imagination, and anatomy becomes art!\\n\\n✨ No previous painting experience needed. Gentle guidance provided throughout.\\n\\nThe workshop includes **four classes**, but you’re also welcome to join individual sessions (when available).\\n\\nTo receive the registration form and full details, please contact:\\n📩 **hola.berlinartclub@gmail.com**\\n\\n**When:**\\nTuesday 7 - 14 - 21 - 28 April\\nFrom 6 to 7.30 PM\\n\\n**Where:**\\nFriedrichshain, Berlin (You will receive the exact address by e-mail)\\n\\n**Price:**\\n85€ for the whole month (4 classes)\\nSingle class 25€ / Paypal & Bank Transfer\\n\\n**Material:**\\nYou will need a watercolour set + watercolour paper + brushes. If you need suggestions about the material, get in touch. If you need some recommendations, this might help:\\n**[Quick Material Guide](https://www.instagram.com/p/DBRDE95Ia5D/?img_index=2)**\\n\\n**To book your spot:**\\nPlease confirm here: **hola.berlinartclub@gmail.com,** and you will receive the payment details and the exact address.\\n***Super small groups! RSVP here is not considered Booked.***\\n\\nYou can find my work [HERE](https://www.instagram.com/lujancordaro/)\\nand all updated classes [HERE ](https://www.instagram.com/berlin.art.club/)\\n\\nSee you!!\\nLu and the BAC"
url: "https://www.meetup.com/berlinartclub/events/313782414/"
date_start: "2026-04-14T18:00:00+02:00"
date_end: "2026-04-14T19:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Grünberger Straße
venue_address: Grünberger Str.
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.512035
venue_lon: 13.455164
organizer_id: "23034610"
organizer_name: Berlin Art Club
organizer_slug: berlinartclub
rsvp_count: 1
is_paid: true
fee_amount: 25.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/c/4/7/5/highres_533210293.jpeg"
hash: 55a730ba2659d604
embed_ref: fantastic-anatomy-watercolour-Sq3
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "0034be8f-7a48-4f4f-8d80-740770e9a4c7",
      type: "event",
      content: `type: event_result
id: "313830937"
provider: meetup
title: Lino Café
description: "Spend a varied and creative Tuesday evening with linocut and linocut printing!\\n\\nThe Lino Café is a space to create, explore and hangout with fellow linocut enthusiasts.\\n\\nAll basic materials and drinks (tea & coffee) are included.\\n\\nThe event is hosted by professional artist Rebeca Ventura (Arte Gorda).\\n\\nSupport is available in English, Portuguese, Spanish, and German upon request.\\n\\nIn order to participate in the Lino Café, you need to feel comfortable with the basics of linocut printing. In case you haven't done lino cut before, just book the option \\"First Timer\\".\\n\\nWe are looking forward to welcoming you there!\\n\\nBooking: **[https://www.tickettailor.com/events/learnlino](https://www.tickettailor.com/events/learnlino)**"
url: "https://www.meetup.com/berlin-art-workshops/events/313830937/"
date_start: "2026-04-14T18:00:00+02:00"
date_end: "2026-04-14T20:00:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: kunstraum heartspace
venue_address: Danziger Straße 172
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.53248
venue_lon: 13.440043
organizer_id: "37683544"
organizer_name: Berlin Art Workshops
organizer_slug: berlin-art-workshops
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/9/d/f/3/highres_533260435.jpeg"
hash: 4a2d1f1b053f4257
embed_ref: lino-caf-51i
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "f0b2ddc3-507b-4533-b99a-dd91377467a2",
      type: "event",
      content: `type: event_result
id: "313784691"
provider: meetup
title: Cozy Life Drawing Session – NAKED ARTISTS Berlin
description: "Join our welcoming **life drawing** session where participants are invited to both draw and model.\\nA relaxed and respectful space for **creative exploration**.\\n\\nThe **Cozy Session** is our most intimate format. We are fewer people (max. 10) and take a bit more time for everything. The atmosphere is calmer and we have even more focus on **presence, observation** and **connection**.\\n\\nAll our events are **queer-friendly** and have a personal and inviting feel to them. Also we're very **beginner-friendly**: Whether you’re experienced or just curious to try life drawing for the first time — you are welcome.\\n\\nGenerally participation in modeling is always **voluntary**, but in this format – since we're fewer people – It's more the idea **that everybody will have** the chance to pose. If you feel more insecure about this, maybe our other sessions are better for a start.\\n\\n**\\\\>\\\\> What to expect**\\n• alternating drawing and modelling\\n• short and medium poses (up to 15 min)\\n• a warm, respectful group atmosphere\\n\\n**\\\\>\\\\> What to bring**\\n• your drawing materials (we provide a basic range of high quality artist materials)\\n• Something small to drink or snack on, though we‘ll have some snacks\\n• your time (Please be punctual because we want to start all together)\\n\\n**\\\\>\\\\> Tickets**\\nOur prices range from **16€ to 26€**, depending on your financial possibilities. Please book your ticket here on **[Eventbrite](https://www.eventbrite.com/e/1985134012269?aff=oddtdtcreator).**\\nYou can also click **RSVP here on Meetup** to let the group know you’re coming.\\n\\nWe look forward to drawing with you!"
url: "https://www.meetup.com/naked-artists-life-drawing-community/events/313784691/"
date_start: "2026-04-14T18:15:00+02:00"
date_end: "2026-04-14T21:45:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Wilhelmine-Gemberg-Weg 14  Wilhelmine-Gemberg-Weg 14 10179 Berlin Germany
venue_address: Wilhelmine-Gemberg-Weg 14  Wilhelmine-Gemberg-Weg 14 10179 Berlin Germany
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.509857
venue_lon: 13.423723
organizer_id: "38228242"
organizer_name: NAKED ARTISTS Berlin – Life Drawing Community
organizer_slug: naked-artists-life-drawing-community
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/d/9/c/7/highres_533215751.jpeg"
hash: 0f5b6427a4880aba
embed_ref: cozy-life-drawing-ASz
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "de2a9800-eb2b-4525-9dd6-d692b5487aae",
      type: "event",
      content: `type: event_result
id: "314184559"
provider: meetup
title: "Klassisches Zeichnen/ Kurs "
description: "Hallo zusammen!\\nIn Rahmen der PAKD Gallery Kurse bieten wir euch einen Zeichenkurs an. Wenn Ihr Zeichnen liebt und eure Fähigkeiten weiterentwickeln möchtet, dann seid Ihr hier genau richtig. In diesem Video erzähle ich euch von meinem Kurs für realistisches Zeichnen mit Bleistift - und wie er Eure künstlerische Arbeit auf ein neues Level bringen kann. Hattest Du schon immer das Gefühl, zeichnen können zu wollen - Dir fehlt aber die richtige Anleitung? In diesem Kurs lernst Du realistisches Zeichnen mit Bleistift, einfach, verständlich und Schritt für Schritt:\\n• Korrekte Perspektive\\n• Licht und Schatten\\n• Materialdarstellung wie Glas, Keramik, Stoff, Metall\\nDer Kurs ist perfekt für Anfänger und für alle, die ihre Fähigkeiten verbessern möchten. Wenn dieses Video Eure Leidenschaft für das Zeichnen mit Bleistift geweckt hat, dann schickt mir einfach eine E-Mail und lasst uns gemeinsam eure Reise in die Welt des realistischen Zeichnens mit Bleistift beginnen.\\nKleiner Kurs, große Wirkung. Maximal 12 Teilnehmer\\\\*innen! Anmeldung:Ä\\n\\n[kifan@pakd-gallery.com](mailto:kifan@pakd-gallery.com)\\nSichere dir deinen Platz, bevor alles ausgebucht ist.\\nDienstag 18:30 - 21:30 Uhr.\\n\\n25€ für eine einzelne 3- stündige Einheit 200€ für ein 10er-Paket, flexibles einlösbar."
url: "https://www.meetup.com/pakd-art-lab-berlin/events/314184559/"
date_start: "2026-04-14T18:30:00+02:00"
date_end: "2026-04-14T21:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: PAKD Gallery Berlin
venue_address: "An Der Mole 9, 10317"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.499825
venue_lon: 13.469001
organizer_id: "37698973"
organizer_name: "Art Classes, Figure Drawing & Portrait Painting @PAKD ArtLab"
organizer_slug: pakd-art-lab-berlin
rsvp_count: 2
is_paid: true
fee_amount: 25.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/9/9/d/a/highres_532479386.jpeg"
hash: 149cf185512771a3
embed_ref: klassisches-zeichnen-kurs-ia6
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "87cc017f-0cc2-40cb-84ac-a8e498331f5c",
      type: "event",
      content: `type: event_result
id: "314106885"
provider: meetup
title: "Realistic Oil Painting Course: Book at www.BerlinPortraitAcademy.com"
description: "* **BOOK HERE: [www.BerlinPortraitAcademy.com](www.BerlinPortraitAcademy.com)**\\n\\n**More information:**\\nBerlin Portrait Academy teaches realistic oil painting in the tradition of academies in Florence, Barcelona and London, bringing the Atelier experience to Berlin. Open to all levels from absolute beginner, to those who are more experienced but interested in tackling the academic method.\\n\\nPlaces are limited to six students per session. Cost is 45 euros per class 350 for a package of ten classes (enquire via email). Materials are provided free for the first lesson.\\n\\n**Please email [peter@pakd-gallery.com](peter@pakd-gallery.com) with any further questions!**\\n\\nSee you there!\\n\\n**[www.BerlinPortraitAcademy.com](www.BerlinPortraitAcademy.com)**"
url: "https://www.meetup.com/pakd-art-lab-berlin/events/314106885/"
date_start: "2026-04-14T18:45:00+02:00"
date_end: "2026-04-14T21:45:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: PAKD Gallery Berlin
venue_address: "An Der Mole 9, 10317"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.499825
venue_lon: 13.469001
organizer_id: "37698973"
organizer_name: "Art Classes, Figure Drawing & Portrait Painting @PAKD ArtLab"
organizer_slug: pakd-art-lab-berlin
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/7/b/2/3/highres_526111523.jpeg"
hash: e91cbe16694b4116
embed_ref: realistic-oil-painting-8b1
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "cf55a429-756a-468b-b37a-918a603d7074",
      type: "event",
      content: `type: event_result
id: "314106891"
provider: meetup
title: "Realistic Oil Painting Course: Book at www.BerlinPortraitAcademy.com"
description: "## Book here: **[www.BerlinPortraitAcademy.com](www.BerlinPortraitAcademy.com)**\\n\\nBerlin Portrait Academy teaches realistic oil painting in the tradition of academies in Florence, Barcelona and London, bringing the Atelier experience to Berlin. Open to all levels from absolute beginner, to those who are more experienced but interested in tackling the academic method.\\n\\nPlaces are limited to six students per session. Cost is 45 euros per class or 350 for a package of ten classes (enquire via email). Materials are provided free for the first lesson.\\n\\n**Please email [peter@pakd-gallery.com](http://peter@pakd-gallery.com/) with any further questions!**\\n\\nSee you there!"
url: "https://www.meetup.com/berlin-drawing-group-classes/events/314106891/"
date_start: "2026-04-14T18:45:00+02:00"
date_end: "2026-04-14T21:45:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: PAKD Gallery Berlin
venue_address: "An d. Mole 9, 10317 Berlin"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.49974
venue_lon: 13.468924
organizer_id: "36067986"
organizer_name: Berlin Drawing Group
organizer_slug: berlin-drawing-group-classes
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/a/9/a/highres_528722714.jpeg"
hash: 797092f0b5a05200
embed_ref: realistic-oil-painting-VR8
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      type: "app_skill_use",
      content: `app_id: events
skill_id: search
result_count: 10
embed_ids: 1a1bc73d-d492-4e4e-8c2d-d4045207a333|296b0b8b-74ad-467e-9c1f-d0d6f72b1b65|a720fd63-e71f-452b-8ce2-680dc0554a9c|69309294-085d-4fa3-81e4-5271d45d5652|0034be8f-7a48-4f4f-8d80-740770e9a4c7|f0b2ddc3-507b-4533-b99a-dd91377467a2|de2a9800-eb2b-4525-9dd6-d692b5487aae|87cc017f-0cc2-40cb-84ac-a8e498331f5c|cf55a429-756a-468b-b37a-918a603d7074|13a405b2-621d-41b1-88a3-9f7aa2262114
status: finished
end_date: "2026-04-19T23:59:59Z"
start_date: "2026-04-13T00:00:00Z"
location: "Berlin, Germany"
query: drawing meetup
id: 1
provider: none
providers: meetup|resident_advisor|luma`,
      parent_embed_id: null,
      embed_ids: [
        "1a1bc73d-d492-4e4e-8c2d-d4045207a333",
        "296b0b8b-74ad-467e-9c1f-d0d6f72b1b65",
        "a720fd63-e71f-452b-8ce2-680dc0554a9c",
        "69309294-085d-4fa3-81e4-5271d45d5652",
        "0034be8f-7a48-4f4f-8d80-740770e9a4c7",
        "f0b2ddc3-507b-4533-b99a-dd91377467a2",
        "de2a9800-eb2b-4525-9dd6-d692b5487aae",
        "87cc017f-0cc2-40cb-84ac-a8e498331f5c",
        "cf55a429-756a-468b-b37a-918a603d7074",
        "13a405b2-621d-41b1-88a3-9f7aa2262114",
      ],
    },
    {
      embed_id: "13a405b2-621d-41b1-88a3-9f7aa2262114",
      type: "event",
      content: `type: event_result
id: "313932891"
provider: meetup
title: "Painting 3D Prints – Busts, Masks, Miniatures"
description: "A 2‑hour painting session focused on colorizing 3D‑printed models.\\n\\n**About this course**\\nThis workshop is designed to introduce participants to the world of painting 3D‑printed objects such as busts, masks, figurines, and miniatures. Whether you want to learn techniques for smooth gradients, realistic textures, weathering, metallic finishes, or character detailing, this course will guide you through every step.\\n\\nYou can join at any time. Each session is self‑contained and suitable for all skill levels. All essential painting materials are provided, and you are welcome to bring your own brushes or paints if you prefer.\\n\\nThe workshop is hosted by visual artist Miltos Despoudis.\\n\\n**How much does it cost?**\\nSee options below:\\nMember Pass (8 × Lessons, 2 hours each): 100 €\\nIncludes:\\n\\n* up to 4 small 3D models of small size to print\\n* special low‑cost 3D printing prices\\n* storage space for your ongoing prints or projects\\n* prepaid lesson tickets are valid for 3 months\\n\\nSingle Drop‑In Pass\\n1 × Lesson (2 hours): 15 €\\n\\n**How do I subscribe?**\\nReserve a spot here and simply show up at the event. Payment is done on‑site. Please confirm your attendance so we can prepare the appropriate materials and printing resources.\\n\\n**What do I need?**\\nAll painting supplies are provided. Optionally you may bring your own 3d print models or art tools.\\n\\nThere will be ready-to-paint small 3d prints at the session. These are given for free. For custom ones you need to book for the Member's Pass.\\n\\n**More Info**\\nSessions happen weekly.\\nLearn more about additional creative workshops here:\\n[creativesessions.art/workshops](https://creativesessions.art/workshops/)\\n\\n**Refund Policy**\\nRefunds are considered on a case‑by‑case basis.\\nIf you booked a Single Drop‑In Pass, refunds are possible up to one day before the event. For the Member Pass, once one session has been used, refunds are not possible."
url: "https://www.meetup.com/creativesessions/events/313932891/"
date_start: "2026-04-14T18:50:00+02:00"
date_end: "2026-04-14T20:50:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: CISpace - Coworking & Weinbar
venue_address: Bugenhagenstraße 9
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.527943
venue_lon: 13.341613
organizer_id: "28869430"
organizer_name: Creative Sessions
organizer_slug: creativesessions
rsvp_count: 4
is_paid: true
fee_amount: 15.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/b/9/1/7/highres_533147383.jpeg"
hash: 1eab34ae1b9abbcf
embed_ref: painting-3d-prints-nLQ
app_id: events
skill_id: search`,
      parent_embed_id: "2adf55c0-1e78-42f4-88b3-ce0bff942110",
      embed_ids: null,
    },
    {
      embed_id: "65f0886d-e9aa-4ae0-8fbe-928b3fd44274",
      type: "app_skill_use",
      content: `app_id: events
skill_id: search
result_count: 10
embed_ids: 707ef95c-b5fb-4094-8757-f3c9a5943438|72502268-d788-4a82-b63c-6c2f38f1e028|f72e1260-99ac-43cd-a236-f05d5c6307b8|39a44531-dcbc-4ec3-a5dd-d1f251f0247b|28197f57-550b-4daa-8503-14fd9d31f5dc|34d41552-fa80-4626-8c73-8dfedfa18d38|a93af071-ac34-4161-af81-68b97f8da3c2|1bf73b29-7328-4783-8ad2-e13dda0b726a|357f3d06-816b-4c89-9b83-fc39d92a4f0d|8aafebba-ad72-4526-be20-760d1e73f6e9
status: finished
end_date: "2026-04-19T23:59:59Z"
query: creativity workshop
location: "Berlin, Germany"
start_date: "2026-04-13T00:00:00Z"
id: 2
provider: none
providers: meetup|resident_advisor|luma`,
      parent_embed_id: null,
      embed_ids: [
        "707ef95c-b5fb-4094-8757-f3c9a5943438",
        "72502268-d788-4a82-b63c-6c2f38f1e028",
        "f72e1260-99ac-43cd-a236-f05d5c6307b8",
        "39a44531-dcbc-4ec3-a5dd-d1f251f0247b",
        "28197f57-550b-4daa-8503-14fd9d31f5dc",
        "34d41552-fa80-4626-8c73-8dfedfa18d38",
        "a93af071-ac34-4161-af81-68b97f8da3c2",
        "1bf73b29-7328-4783-8ad2-e13dda0b726a",
        "357f3d06-816b-4c89-9b83-fc39d92a4f0d",
        "8aafebba-ad72-4526-be20-760d1e73f6e9",
      ],
    },
    {
      embed_id: "02af5424-29c2-4a75-8102-82b82cd43f01",
      type: "event",
      content: `type: event_result
id: "2388245"
provider: resident_advisor
title: "manic.monday mit Leeroyyal, Fif, RX & Demar"
description: "Lineup: RX (1), Demar\\nYou wanna spend a night with Electronic Beats,Ping Pong & nice Drinks? A Dance Floor & creative cosy chill Areas? Come to our Minimal Bar!! Here you will have fancy Drinks & cool Bar-Tenders, daily Electronic life DJ's, Berlin Art and heaps of Fun in our Table-Tennis Area. No Racism. No Sexism. No Homophobia. No Transphobia. No Discrimination of any kind.\\n"
url: "https://ra.co/events/2388245"
date_start: "2026-04-05T18:00:00.000"
date_end: "2026-04-15T05:00:00.000"
timezone: null
event_type: PHYSICAL
venue_name: Minimal Bar
venue_address: Rigaer Strasse 31; Friedrichshain; 10247 Berlin; Germany
venue_city: Berlin
venue_state: null
venue_country: null
venue_lat: 52.51639
venue_lon: 13.46406
organizer_name: mini.mal elektrokneipe
organizer_slug: null
organizer_id: null
rsvp_count: 17
is_paid: false
fee: null
image_url: "https://images.ra.co/8f9e37de7436e53d18591b0f1da49807a9edd930.jpg"
artists: RX (1)|Demar
genres: null
minimum_age: 21
is_festival: false
hash: 4209eef79dc65ad6
embed_ref: manic-monday-mit-tlR
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "7f3ae6f5-b825-4188-8056-354b189ec8e4",
      type: "event",
      content: `type: event_result
id: "313907649"
provider: meetup
title: "Watercolours for Beginners - Practise Group "
description: "If you’re just starting out with watercolours—maybe you’ve painted a bit at home or followed a tutorial or two, but still feel a little lost—I think you’re going to like this!\\n\\nFirst, we’ll practice **wet-on-wet, layering washes, colour mixing, transparency** and more. After this first part of the class, once you’ve discovered a few watercolour effects, you’ll have time to practise them by applying them to simple shapes (animals, plants, etc.) that I’ll provide. With the help of examples—and my guidance, of course—you’ll practise alongside other watercolour enthusiasts, supporting and learning from one another. Feel free to bring ideas and questions about things you'd like to paint :)\\n\\n**No previous experience needed**—just curiosity and a willingness to explore.\\n\\n###\\n\\n**Mondays 13 - 20 April** from 6:00 to 7:30 PM\\n**In Friedrichshain**, Berlin (exact address by e-mail)\\nJoin us for one or both classes, as you prefer. They are independent but complementary.\\n\\n**Price:**\\n\\n* 27€ x class / 50€ x 2 classes\\nPayment via PayPal / Bank transfer\\n\\n**Material:**\\nMaterial for watercolours is very specific. If you use poor-quality or non-professional material, you won't achieve the optimal results.\\n\\nPlease check this helpful guide:\\n[https://www.instagram.com/p/CKWdOx6FczD/](https://www.instagram.com/p/CKWdOx6FczD/)\\n\\n* I recommend bringing your own material so you can keep practising at home after the classes. If you don't want to buy it, I can also lend it to you for a small extra fee of 5€. Please let me know in advance.\\n\\n###\\n\\n**Booking by email only:**\\nEmail: **hola.berlinartclub@gmail.com**\\nYou’ll receive payment details and the exact address upon confirmation.\\n\\n🎟 **Spaces are limited—join us!**\\nRSVP here does not save you a spot.\\n\\nwww.lujancordaro.com\\n[@lujancordaro](www.instagram.com/lujancordaro)\\n[@berlin.art.club](www.instagram.com/berlin.art.club)"
url: "https://www.meetup.com/berlinartclub/events/313907649/"
date_start: "2026-04-13T18:00:00+02:00"
date_end: "2026-04-13T19:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Grünberger Straße
venue_address: Grünberger Str.
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.512035
venue_lon: 13.455164
organizer_id: "23034610"
organizer_name: Berlin Art Club
organizer_slug: berlinartclub
rsvp_count: 3
is_paid: true
fee_amount: 27.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/e/2/7/7/highres_533217975.jpeg"
hash: 249fba2c27f506fd
embed_ref: watercolours-for-beginners-riE
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "672a68f1-a734-4ec7-8901-1e133db353a6",
      type: "event",
      content: `type: event_result
id: "2388247"
provider: resident_advisor
title: manic.monday mit Gui Zellermayer !FREE ENTRY
description: "Lineup: Gui Zellermayer\\nYou wanna spend a night with Electronic Beats,Ping Pong & nice Drinks? A Dance Floor & creative cosy chill Areas? Come to our Minimal Bar!! Here you will have fancy Drinks & cool Bar-Tenders, daily Electronic life DJ's, Berlin Art and heaps of Fun in our Table-Tennis Area. No Racism. No Sexism. No Homophobia. No Transphobia. No Discrimination of any kind.\\n"
url: "https://ra.co/events/2388247"
date_start: "2026-04-13T18:00:00.000"
date_end: "2026-04-14T04:00:00.000"
timezone: null
event_type: PHYSICAL
venue_name: Minimal Bar
venue_address: Rigaer Strasse 31; Friedrichshain; 10247 Berlin; Germany
venue_city: Berlin
venue_state: null
venue_country: null
venue_lat: 52.51639
venue_lon: 13.46406
organizer_name: mini.mal elektrokneipe
organizer_slug: null
organizer_id: null
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://images.ra.co/7e4f95836f9b112571b453d7d2e06040c66e9504.jpg"
artists: Gui Zellermayer
genres: null
minimum_age: 21
is_festival: false
hash: 2c25fee6f306b319
embed_ref: manic-monday-mit-W52
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "19a0f5a3-b44e-477e-be86-0b2bc5ff33ad",
      type: "event",
      content: `type: event_result
id: "312643653"
provider: meetup
title: JCD - Martial Arts Training - Grappling
description: "Join us for a thrilling and empowering Martial Arts Training hosted by the **Juk Cheon Do** \\\\- Self Defense and Martial Arts group\\\\!\\n\\nOur monday training is focused on **Grappling.**\\n\\nThis event is perfect for adults looking to enhance their self-defense techniques, improve fitness, and learn this unique Korean German Martial Art. Whether you are a newbie or have experience in MMA Mixed Martial Arts, BJJ, Judo, Wrestling or Sambo, this training will offer valuable insights and practical training exercises to bring your skills to another level.\\n\\nGet ready to boost your confidence, strength, and agility while embracing the physical and mental challenges of this martial arts training and enjoy this fantastic opportunity to make new friends within the community of like-minded individuals who share a passion for martial arts.\\nWe are not a huge group and like to train in a nice atmosphere with each other.\\n\\nEverybody is welcome weather you are a total beginner or experienced martial artist, weather your are top fit or you want to be it. Don’t be afraid and never forget, everybody starts at one point as a beginner. Important is the will to start. So no excuses! Start today!\\n\\nAnd of course we are also open to females, males and whatever. Here everybody is equal to share the same fun and pain. ;)\\n\\nLanguages: German, English, Korean, Japanese.\\n\\nIf the door is closed or you can’t find us, please call me: 01781830004 !"
url: "https://www.meetup.com/juk-cheon-do-self-defense-martial-arts/events/312643653/"
date_start: "2026-04-13T18:45:00+02:00"
date_end: "2026-04-13T21:15:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Juk Cheon Do Berlin - Schule für Kampfkunst und Kultur
venue_address: "Pankstraße 12,"
venue_city: Berlin
venue_state: ""
venue_country: DE
venue_lat: 52.5458
venue_lon: 13.371419
organizer_id: "36215499"
organizer_name: Juk Cheon Do - Self Defense and Martial Arts
organizer_slug: juk-cheon-do-self-defense-martial-arts
rsvp_count: 7
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/c/4/6/3/highres_502790275.jpeg"
hash: db39f51648013917
embed_ref: jcd-martial-arts-P8w
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "8eefc99c-e739-4488-bbbd-114129840521",
      type: "event",
      content: `type: event_result
id: "313944512"
provider: meetup
title: "Collaborative Drawing & Printing group, Rhinower Str 10, 10437. Just try it!!!"
description: "Communicative, collaborative and creative drawing sessions. Participants draw a central still-life that the group can create themselves until the music track finishes and then pass it to the person on their left. The drawings change hands 3 to 5 times and the end results are always inspiring. After the collaborative warm-up participants can work individually on printing techniques, Mono -printing, tetra-pack or gelli. -printing. Feel free to try out a process that you are unfamiliar with. There will always be somebody to offer advice if necessary Bring A4 paper, and favourite materials, pencils & brushes. You can also use some studio materials in exchange for a small contribution. A fun but informative approach with consistently creative results!"
url: "https://www.meetup.com/ww-alexinegood-de/events/313944512/"
date_start: "2026-04-14T18:00:00+02:00"
date_end: "2026-04-14T19:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Studio Good
venue_address: "Rhinowerstr.10, Rhinowerstr.10"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.548176
venue_lon: 13.409631
organizer_id: "36285637"
organizer_name: Rhinower 10 Studio/ Art & Language
organizer_slug: ww-alexinegood-de
rsvp_count: 1
is_paid: true
fee_amount: 20.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/4/e/3/6/highres_514820022.jpeg"
hash: 2d7b2a880a7b080a
embed_ref: collaborative-drawing-printing-LhO
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "f4679943-0679-431f-bd61-868fd5a709e6",
      type: "event",
      content: `type: event_result
id: "313782414"
provider: meetup
title: Fantastic Anatomy Watercolour Workshop
description: "### **Fantastic Anatomy**\\n\\nIn this unique workshop, we will explore and celebrate the human body in all its beautiful complexity — and then let our imagination transform it.\\n\\nWhat does a sacrum look like? Could it become a butterfly?\\nHow do hands truly connect? Can we paint the magic of a gentle touch?\\nWhat lives in our hearts?\\n\\nTogether, we will observe the body with curiosity and appreciation, and then reimagine it through colour and fantasy. This workshop is an invitation to experience the body not only as anatomy, but as a living, poetic vessel that carries us through life.\\n\\nOver four classes, we will explore bones, muscles, and organs in a fresh and expressive way. Using watercolour techniques that embrace fluidity and transparency, we’ll experiment with water, stains, textures, and layering to create our own artistic vision of the body.\\n\\nJoin me in this colourful tribute to the extraordinary vessel we inhabit — where science meets imagination, and anatomy becomes art!\\n\\n✨ No previous painting experience needed. Gentle guidance provided throughout.\\n\\nThe workshop includes **four classes**, but you’re also welcome to join individual sessions (when available).\\n\\nTo receive the registration form and full details, please contact:\\n📩 **hola.berlinartclub@gmail.com**\\n\\n**When:**\\nTuesday 7 - 14 - 21 - 28 April\\nFrom 6 to 7.30 PM\\n\\n**Where:**\\nFriedrichshain, Berlin (You will receive the exact address by e-mail)\\n\\n**Price:**\\n85€ for the whole month (4 classes)\\nSingle class 25€ / Paypal & Bank Transfer\\n\\n**Material:**\\nYou will need a watercolour set + watercolour paper + brushes. If you need suggestions about the material, get in touch. If you need some recommendations, this might help:\\n**[Quick Material Guide](https://www.instagram.com/p/DBRDE95Ia5D/?img_index=2)**\\n\\n**To book your spot:**\\nPlease confirm here: **hola.berlinartclub@gmail.com,** and you will receive the payment details and the exact address.\\n***Super small groups! RSVP here is not considered Booked.***\\n\\nYou can find my work [HERE](https://www.instagram.com/lujancordaro/)\\nand all updated classes [HERE ](https://www.instagram.com/berlin.art.club/)\\n\\nSee you!!\\nLu and the BAC"
url: "https://www.meetup.com/berlinartclub/events/313782414/"
date_start: "2026-04-14T18:00:00+02:00"
date_end: "2026-04-14T19:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Grünberger Straße
venue_address: Grünberger Str.
venue_city: Berlin
venue_state: BE
venue_country: de
venue_lat: 52.512035
venue_lon: 13.455164
organizer_id: "23034610"
organizer_name: Berlin Art Club
organizer_slug: berlinartclub
rsvp_count: 1
is_paid: true
fee_amount: 25.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/c/4/7/5/highres_533210293.jpeg"
hash: 55a730ba2659d604
embed_ref: fantastic-anatomy-watercolour-BXh
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "0e78a379-4776-4414-9ba0-aa23bd2d46fd",
      type: "event",
      content: `type: event_result
id: "2388248"
provider: resident_advisor
title: go.play mit Flip Marlou. & Melihsub !FREE ENTRY
description: "You wanna spend a night with Electronic Beats,Ping Pong & nice Drinks? A Dance Floor & creative cosy chill Areas? Come to our Minimal Bar!! Here you will have fancy Drinks & cool Bar-Tenders, daily Electronic life DJ's, Berlin Art and heaps of Fun in our Table-Tennis Area. No Racism. No Sexism. No Homophobia. No Transphobia. No Discrimination of any kind.\\n"
url: "https://ra.co/events/2388248"
date_start: "2026-04-14T18:00:00.000"
date_end: "2026-04-15T04:00:00.000"
timezone: null
event_type: PHYSICAL
venue_name: Minimal Bar
venue_address: Rigaer Strasse 31; Friedrichshain; 10247 Berlin; Germany
venue_city: Berlin
venue_state: null
venue_country: null
venue_lat: 52.51639
venue_lon: 13.46406
organizer_name: mini.mal elektrokneipe
organizer_slug: null
organizer_id: null
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://images.ra.co/399f546af109b567ed3348c41c454dcee354d4b5.jpg"
artists: null
genres: null
minimum_age: 21
is_festival: false
hash: 7a04c51de15b9c01
embed_ref: go-play-mit-0uH
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "f54ac9a9-c57e-4ada-b41c-e1f6d8630577",
      type: "event",
      content: `type: event_result
id: "313784691"
provider: meetup
title: Cozy Life Drawing Session – NAKED ARTISTS Berlin
description: "Join our welcoming **life drawing** session where participants are invited to both draw and model.\\nA relaxed and respectful space for **creative exploration**.\\n\\nThe **Cozy Session** is our most intimate format. We are fewer people (max. 10) and take a bit more time for everything. The atmosphere is calmer and we have even more focus on **presence, observation** and **connection**.\\n\\nAll our events are **queer-friendly** and have a personal and inviting feel to them. Also we're very **beginner-friendly**: Whether you’re experienced or just curious to try life drawing for the first time — you are welcome.\\n\\nGenerally participation in modeling is always **voluntary**, but in this format – since we're fewer people – It's more the idea **that everybody will have** the chance to pose. If you feel more insecure about this, maybe our other sessions are better for a start.\\n\\n**\\\\>\\\\> What to expect**\\n• alternating drawing and modelling\\n• short and medium poses (up to 15 min)\\n• a warm, respectful group atmosphere\\n\\n**\\\\>\\\\> What to bring**\\n• your drawing materials (we provide a basic range of high quality artist materials)\\n• Something small to drink or snack on, though we‘ll have some snacks\\n• your time (Please be punctual because we want to start all together)\\n\\n**\\\\>\\\\> Tickets**\\nOur prices range from **16€ to 26€**, depending on your financial possibilities. Please book your ticket here on **[Eventbrite](https://www.eventbrite.com/e/1985134012269?aff=oddtdtcreator).**\\nYou can also click **RSVP here on Meetup** to let the group know you’re coming.\\n\\nWe look forward to drawing with you!"
url: "https://www.meetup.com/naked-artists-life-drawing-community/events/313784691/"
date_start: "2026-04-14T18:15:00+02:00"
date_end: "2026-04-14T21:45:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: Wilhelmine-Gemberg-Weg 14  Wilhelmine-Gemberg-Weg 14 10179 Berlin Germany
venue_address: Wilhelmine-Gemberg-Weg 14  Wilhelmine-Gemberg-Weg 14 10179 Berlin Germany
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.509857
venue_lon: 13.423723
organizer_id: "38228242"
organizer_name: NAKED ARTISTS Berlin – Life Drawing Community
organizer_slug: naked-artists-life-drawing-community
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/d/9/c/7/highres_533215751.jpeg"
hash: 0f5b6427a4880aba
embed_ref: cozy-life-drawing-XSs
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "a81d1c35-5cb2-44da-a271-25cab8e8c231",
      type: "event",
      content: `type: event_result
id: "314184559"
provider: meetup
title: "Klassisches Zeichnen/ Kurs "
description: "Hallo zusammen!\\nIn Rahmen der PAKD Gallery Kurse bieten wir euch einen Zeichenkurs an. Wenn Ihr Zeichnen liebt und eure Fähigkeiten weiterentwickeln möchtet, dann seid Ihr hier genau richtig. In diesem Video erzähle ich euch von meinem Kurs für realistisches Zeichnen mit Bleistift - und wie er Eure künstlerische Arbeit auf ein neues Level bringen kann. Hattest Du schon immer das Gefühl, zeichnen können zu wollen - Dir fehlt aber die richtige Anleitung? In diesem Kurs lernst Du realistisches Zeichnen mit Bleistift, einfach, verständlich und Schritt für Schritt:\\n• Korrekte Perspektive\\n• Licht und Schatten\\n• Materialdarstellung wie Glas, Keramik, Stoff, Metall\\nDer Kurs ist perfekt für Anfänger und für alle, die ihre Fähigkeiten verbessern möchten. Wenn dieses Video Eure Leidenschaft für das Zeichnen mit Bleistift geweckt hat, dann schickt mir einfach eine E-Mail und lasst uns gemeinsam eure Reise in die Welt des realistischen Zeichnens mit Bleistift beginnen.\\nKleiner Kurs, große Wirkung. Maximal 12 Teilnehmer\\\\*innen! Anmeldung:Ä\\n\\n[kifan@pakd-gallery.com](mailto:kifan@pakd-gallery.com)\\nSichere dir deinen Platz, bevor alles ausgebucht ist.\\nDienstag 18:30 - 21:30 Uhr.\\n\\n25€ für eine einzelne 3- stündige Einheit 200€ für ein 10er-Paket, flexibles einlösbar."
url: "https://www.meetup.com/pakd-art-lab-berlin/events/314184559/"
date_start: "2026-04-14T18:30:00+02:00"
date_end: "2026-04-14T21:30:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: PAKD Gallery Berlin
venue_address: "An Der Mole 9, 10317"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.499825
venue_lon: 13.469001
organizer_id: "37698973"
organizer_name: "Art Classes, Figure Drawing & Portrait Painting @PAKD ArtLab"
organizer_slug: pakd-art-lab-berlin
rsvp_count: 2
is_paid: true
fee_amount: 25.0
fee_currency: EUR
image_url: "https://secure.meetupstatic.com/photos/event/9/9/d/a/highres_532479386.jpeg"
hash: 149cf185512771a3
embed_ref: klassisches-zeichnen-kurs-SDM
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "d042338d-900b-45df-bff9-ea205b3dce56",
      type: "event",
      content: `type: event_result
id: "314106885"
provider: meetup
title: "Realistic Oil Painting Course: Book at www.BerlinPortraitAcademy.com"
description: "* **BOOK HERE: [www.BerlinPortraitAcademy.com](www.BerlinPortraitAcademy.com)**\\n\\n**More information:**\\nBerlin Portrait Academy teaches realistic oil painting in the tradition of academies in Florence, Barcelona and London, bringing the Atelier experience to Berlin. Open to all levels from absolute beginner, to those who are more experienced but interested in tackling the academic method.\\n\\nPlaces are limited to six students per session. Cost is 45 euros per class 350 for a package of ten classes (enquire via email). Materials are provided free for the first lesson.\\n\\n**Please email [peter@pakd-gallery.com](peter@pakd-gallery.com) with any further questions!**\\n\\nSee you there!\\n\\n**[www.BerlinPortraitAcademy.com](www.BerlinPortraitAcademy.com)**"
url: "https://www.meetup.com/pakd-art-lab-berlin/events/314106885/"
date_start: "2026-04-14T18:45:00+02:00"
date_end: "2026-04-14T21:45:00+02:00"
timezone: Europe/Berlin
event_type: PHYSICAL
venue_name: PAKD Gallery Berlin
venue_address: "An Der Mole 9, 10317"
venue_city: Berlin
venue_state: ""
venue_country: de
venue_lat: 52.499825
venue_lon: 13.469001
organizer_id: "37698973"
organizer_name: "Art Classes, Figure Drawing & Portrait Painting @PAKD ArtLab"
organizer_slug: pakd-art-lab-berlin
rsvp_count: 1
is_paid: false
fee: null
image_url: "https://secure.meetupstatic.com/photos/event/7/b/2/3/highres_526111523.jpeg"
hash: e91cbe16694b4116
embed_ref: realistic-oil-painting-Wb0
app_id: events
skill_id: search`,
      parent_embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      embed_ids: null,
    },
    {
      embed_id: "21ca5a92-705a-46c2-b6f8-a5cfd030dc14",
      type: "app_skill_use",
      content: `app_id: events
skill_id: search
result_count: 10
embed_ids: 02af5424-29c2-4a75-8102-82b82cd43f01|7f3ae6f5-b825-4188-8056-354b189ec8e4|672a68f1-a734-4ec7-8901-1e133db353a6|19a0f5a3-b44e-477e-be86-0b2bc5ff33ad|8eefc99c-e739-4488-bbbd-114129840521|f4679943-0679-431f-bd61-868fd5a709e6|0e78a379-4776-4414-9ba0-aa23bd2d46fd|f54ac9a9-c57e-4ada-b41c-e1f6d8630577|a81d1c35-5cb2-44da-a271-25cab8e8c231|d042338d-900b-45df-bff9-ea205b3dce56
status: finished
end_date: "2026-04-19T23:59:59Z"
start_date: "2026-04-13T00:00:00Z"
location: "Berlin, Germany"
query: art sketching meetup
id: 3
provider: none
providers: meetup|resident_advisor|luma`,
      parent_embed_id: null,
      embed_ids: [
        "02af5424-29c2-4a75-8102-82b82cd43f01",
        "7f3ae6f5-b825-4188-8056-354b189ec8e4",
        "672a68f1-a734-4ec7-8901-1e133db353a6",
        "19a0f5a3-b44e-477e-be86-0b2bc5ff33ad",
        "8eefc99c-e739-4488-bbbd-114129840521",
        "f4679943-0679-431f-bd61-868fd5a709e6",
        "0e78a379-4776-4414-9ba0-aa23bd2d46fd",
        "f54ac9a9-c57e-4ada-b41c-e1f6d8630577",
        "a81d1c35-5cb2-44da-a271-25cab8e8c231",
        "d042338d-900b-45df-bff9-ea205b3dce56",
      ],
    },
  ],
  metadata: {
    featured: true,
    order: 6,
  },
};
