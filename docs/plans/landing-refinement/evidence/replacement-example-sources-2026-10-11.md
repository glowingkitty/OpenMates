# Landing replacement example source review (2026-10-11)

These five candidates use real saved OpenMates chats. This is source and content
review evidence; phone and laptop browser admission remains a separate CI gate.
No share encryption keys, private generated-asset paths, or connected-account
data are retained here.

| App | Public example ID | Source chat | Source observation |
| --- | --- | --- | --- |
| Travel | `example-deutschlandticket-train-fare-breakdown` | `4c2890f0-edf4-4ed2-bdcf-16c6818528bf` | Natural Bonn to Munich train request; finished `travel.search_connections` returned five Deutschlandticket-covered regional connections. This is a dated itinerary from August 2026, not a current timetable. |
| Maps | `example-berlin-mitte-work-friendly` | `3c196d6e-b2bf-4c5d-93f6-d5db5d053844` | Natural Berlin Mitte restaurant request; finished `maps.search` returned mapped places. The answer distinguishes known place details from unknown air-conditioning and Wi-Fi availability. |
| Audio | `example-community-garden-volunteer-chime` | `b304d77b-b27a-4168-9590-029de097b1c4` | Natural request for a gentle two-note signup sound; finished `audio.generate` returned an ElevenLabs sound effect. The exact source asset was downloaded through the owner-authenticated generated-asset endpoint and published as the local public MP3, with private encryption and storage fields removed from example data. |
| Videos | `example-ted-talk-transcript-summary` | `0828c4f9-ee63-4115-992f-6e42c85ce37d` | Natural request using a real YouTube URL; finished `videos.get_transcript` returned timestamped talk text, and the answer provides the requested five-point summary. |
| Calendar | `example-calendar-week-from-supplied` | `e36cb914-f861-4ca9-9e22-82b6033a63f5` | Natural request supplies fictional week events in the message. The answer accurately identifies Wednesday as having the most commitments and Thursday/Sunday as clear. This example does not call `calendar.get-events` or imply connected-calendar access. |

The calendar source explicitly selected George. Three earlier automatic-routing
candidates were rejected because the assistant routed a calendar summary to
the life-coach mate and appended an unrelated mental-health disclaimer. The
selected transcript was extracted from the real CLI chat without editing the
conversation. The audio source finished with a playable 2.038-second MP3;
SHA-256 of `frontend/apps/web_app/static/store-examples/community-garden-volunteer-chime.mp3`
is `e1c045df9ea67291947060c02d4c64c7016d2d58b4170c40245bfcc5ea6b83f6`.
The audio and video assistant messages retain their original response prose and
saved tool outputs. Their source embed UUID references are expressed as public
chat embed links so the interactive renderer displays the real artifact cards.
