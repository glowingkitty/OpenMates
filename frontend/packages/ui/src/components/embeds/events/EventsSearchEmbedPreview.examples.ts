/**
 * App-store examples for the events skill.
 *
 * Captured from real Meetup/Luma/Google Events responses, trimmed to 4 events per query.
 */

export interface EventsSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: EventsSearchStoreExample[] = [
  {
    "id": "store-example-events-search-1",
    "query": "Tech conferences in San Francisco",
    "query_translation_key": "settings.app_store_examples.events.search.1",
    "provider": "none",
    "status": "finished",
    "results": [
      {
        "id": "2403766",
        "provider": "resident_advisor",
        "title": "Danza Wax with GMDS, Owen Irish, Elegance Of The Damned + TSD",
        "description": "Lineup: GMDS, Elegance Of The Damned\nGenres: Acid, Tech House\nDanza Wax takeover at komunal\n\nfree entry below moor street station no ticket required just come x",
        "url": "https://ra.co/events/2403766",
        "date_start": "2026-04-11T19:00:00.000",
        "date_end": "2026-04-12T03:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "komunal",
          "address": "11 Shaw's Passage, Digbeth, B5 5JG",
          "city": "Birmingham",
          "lat": 0,
          "lon": 0
        },
        "organizer": {
          "name": "komrad"
        },
        "rsvp_count": 1,
        "is_paid": true,
        "fee": {
          "amount": "0",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/cf6a6952727ddbd75abb5e5db4ffec1146b3859c.png",
        "genres": [
          "Acid",
          "Tech House"
        ]
      },
      {
        "id": "2383476",
        "provider": "resident_advisor",
        "title": "Club Makumba invites Pluralist",
        "description": "Lineup: Pluralist (UK), Princess Trium\nGenres: Club, Electronica\nClub Makumba takes over The Model for a night where rhythms rule.\n\nExpect a sound system loaded with UK funky, techno, broken rhythms, global club, gqom, afrohouse, bass, baile funk, Jersey club, Latin club, ghetto tech, batida, and afrobeats, a full spectrum of the world’s dancefloor energy.\n\nBristol’s Pluralist headlines with percu",
        "url": "https://ra.co/events/2383476",
        "date_start": "2026-04-11T22:00:00.000",
        "date_end": "2026-04-12T03:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "The Model",
          "address": "23 Goose Gate, Nottingham, NG1 3FE",
          "city": "Nottingham",
          "lat": 52.95,
          "lon": -1.14
        },
        "organizer": {
          "name": "Club Makumba"
        },
        "rsvp_count": 85,
        "is_paid": true,
        "fee": {
          "amount": "7£ - 10£ - 12£",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/1fd69b2f8b9ee1fbf8f6b39b90af5bc49e48ae7b.png",
        "genres": [
          "Club",
          "Electronica"
        ]
      },
      {
        "id": "2412877",
        "provider": "resident_advisor",
        "title": "BRTHx",
        "description": "Genres: Afro House, Afro Tech\nBRTHx returns for another late-night gathering in the shadows of Birmingham.\n\nA stripped-back session focused on sound, atmosphere, and connection where the energy builds slowly and carries through till late.",
        "url": "https://ra.co/events/2412877",
        "date_start": "2026-04-11T23:00:00.000",
        "date_end": "2026-04-12T05:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "TBA",
          "city": "Birmingham",
          "lat": 0,
          "lon": 0
        },
        "organizer": {
          "name": "BRTHx"
        },
        "rsvp_count": 5,
        "is_paid": true,
        "fee": {
          "amount": "0.00",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/beff6fd40942074f5f05aa8ab610e5ba47e6e936.jpg",
        "genres": [
          "Afro House",
          "Afro Tech"
        ]
      },
      {
        "id": "313931456",
        "provider": "meetup",
        "title": "Silicon Valley Business Networking (Online) ",
        "description": "**Organizational Sponsor:**\n\n**Startup House**\n\n**Need a place to stay short term in Silicon Valley?**\n\n**Stay at Startup House in Palo Alto - the heart of Silicon Valley - for as low as $50 a night!**\n\n**-Network, socialize and connect with entrepreneurs all over the world!**\n\n**-Enjoy social events and startup and venture capital-related programming!**\n\n**\\- Have access to world class amenities\\",
        "url": "https://www.meetup.com/tech-and-venture-capital/events/313931456/",
        "date_start": "2026-04-13T12:00:00-07:00",
        "date_end": "2026-04-13T13:00:00-07:00",
        "timezone": "America/Los_Angeles",
        "event_type": "ONLINE",
        "venue": {
          "name": "Online event",
          "address": "",
          "city": "",
          "state": "",
          "country": "",
          "lat": -8.521147,
          "lon": 179.1962
        },
        "organizer": {
          "id": "1503379",
          "name": "Silicon Valley Tech and Venture Capital",
          "slug": "tech-and-venture-capital"
        },
        "rsvp_count": 1,
        "is_paid": false,
        "image_url": "https://secure.meetupstatic.com/photos/event/b/9/f/c/highres_516107612.jpeg"
      }
    ]
  },
  {
    "id": "store-example-events-search-2",
    "query": "Live music concerts in Berlin",
    "query_translation_key": "settings.app_store_examples.events.search.2",
    "provider": "none",
    "status": "finished",
    "results": [
      {
        "id": "2380787",
        "provider": "resident_advisor",
        "title": "TB10: Touching Bass meets SHUSH",
        "description": "RA Pick: Touching Bass mark 10 years with a Shush weekender: Table Farrah dining, an Ebo Taylor tribute live show, then a deep-soul dance with Errol, Naima Adams and more.\nLineup: D'Monk, Errol, Ken Okuda, Maxwell Owin, Naima Adams\nGenres: Deep House, Funk / Soul\nLOCATION DETAILS:\n\nAn d. Michaelbrücke 1\n10179 Berlin\n\nFrom the street An d. Michaelbrücke, you need to enter the big gate at the entran",
        "url": "https://ra.co/events/2380787",
        "date_start": "2026-04-10T18:00:00.000",
        "date_end": "2026-04-12T06:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "TBA - Secret Location",
          "city": "Berlin",
          "lat": 0,
          "lon": 0
        },
        "organizer": {
          "name": "Touching Bass"
        },
        "rsvp_count": 109,
        "is_paid": true,
        "fee": {
          "amount": "15-25",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/fc7d5365ad11c2d5f1ceb45bc5d1bdce8bc265dc.jpg",
        "genres": [
          "Deep House",
          "Funk / Soul"
        ]
      },
      {
        "id": "2394154",
        "provider": "resident_advisor",
        "title": "wake & shake - Coffee Rave Berlin - Vol 2.0",
        "description": "Lineup: NAIR (IN), Dj OmarO, Amed Nheiro\nGenres: House, Afro House\nBerlin, it’s time to trade hangovers for high energy.\n\nwake & shake invites you to the ultimate daytime Coffee Rave at SaBar in Kreuzberg, where specialty coffee meets deep, groovy house beats.\n\nFrom 11 AM to 5 PM, we’re serving caffeine, community and carefully selected house music to kickstart your weekend the right way.\n\nOur DJs",
        "url": "https://ra.co/events/2394154",
        "date_start": "2026-04-11T11:00:00.000",
        "date_end": "2026-04-11T17:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Sabar",
          "address": "Muskauer Str. 6, 10997 Berlin",
          "city": "Berlin",
          "lat": 52.5,
          "lon": 13.43
        },
        "organizer": {
          "name": "wake & shake"
        },
        "rsvp_count": 18,
        "is_paid": true,
        "fee": {
          "amount": "5 € - 8 €",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/b8c8cfd2b3d13f30a25494fc0c427eddfce3c9df.png",
        "genres": [
          "House",
          "Afro House"
        ]
      },
      {
        "id": "2411191",
        "provider": "resident_advisor",
        "title": "RESONANCE｜Späti Takeover - All Day Long -",
        "description": "Lineup: Emilion Dollar Baby, FREEGO, Kazuki Takahashi, Zutri\nGenres: Techno, House\nRESONANCE is taking over VIP SPÄTI on April 11th for our biggest session yet.\nNo guestlist. Just open doors and pure energy.\n\nWHAT IS RESONANCE? \nWe are more than just a party. RESONANCE is a collective where club culture meets live creation. While the DJs control the frequency, non-musical artists (photographers, p",
        "url": "https://ra.co/events/2411191",
        "date_start": "2026-04-11T15:00:00.000",
        "date_end": "2026-04-12T00:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "TBA - VIP Späti, Neukölln",
          "city": "Berlin",
          "lat": 0,
          "lon": 0
        },
        "organizer": {
          "name": "RESONANCE.BERLIN"
        },
        "rsvp_count": 22,
        "is_paid": true,
        "fee": {
          "amount": "0",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/ba951adcf9fe4cca72c25b3caf3cd5cb756c0a46.png",
        "genres": [
          "Techno",
          "House"
        ]
      },
      {
        "id": "2392648",
        "provider": "resident_advisor",
        "title": "KONTRAST // Spring Rooftop Session",
        "description": "Lineup: Dilby, Leah Marie, Esin, Andrea Chiovelli, Rune Steen\nGenres: House, Deep House\nKONTRAST // Back In Bloom\nSpring Rooftop Session\n\nWeatherproof rooftop with retractable cover. A cosy setting in any weather!\n\nAn afternoon and evening of deep, groovy house music in a warm, social setting above the river. A space for people who love underground house music, good sound, good drinks and a welcom",
        "url": "https://ra.co/events/2392648",
        "date_start": "2026-04-11T16:00:00.000",
        "date_end": "2026-04-11T23:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Amano East-Side",
          "address": "Stralauer Pl. 30-31, 10243 Berlin, Germany",
          "city": "Berlin",
          "lat": 53,
          "lon": 13
        },
        "organizer": {
          "name": "Kontrast Events"
        },
        "rsvp_count": 270,
        "is_paid": true,
        "image_url": "https://images.ra.co/579933cd20ae5cbde0274132fffd4c753d3f636a.jpg",
        "genres": [
          "House",
          "Deep House"
        ]
      }
    ]
  },
  {
    "id": "store-example-events-search-3",
    "query": "Art exhibitions in London",
    "query_translation_key": "settings.app_store_examples.events.search.3",
    "provider": "none",
    "status": "finished",
    "results": [
      {
        "id": "2366770",
        "provider": "resident_advisor",
        "title": "The Ultimate Rave Celebration",
        "description": "Lineup: Ratpack, Billy Daniel Bunter, T-Cuts, Swankout, Krome, Nookie (UK), Madcap, Squirrel, Jay Cunning, Five Alive\nGenres: Breakbeat, Drum & Bass\nOne huge celebration across 8 arenas. The Epidemik 31st Birthday, the return of The Rave Story and the launch of the Billy Daniel Bunter extended set.\n\nWe will be using the Electrowerkz to the fullest with 4 arenas of raving and 4 arenas of art galler",
        "url": "https://ra.co/events/2366770",
        "date_start": "2026-04-11T12:00:00.000",
        "date_end": "2026-04-11T21:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Electrowerkz",
          "address": "7 Torrens Street; Islington; London EC1V 1NQ; United Kingdom",
          "city": "London",
          "lat": 51.532528,
          "lon": -0.105192
        },
        "organizer": {
          "name": "Music Mondays"
        },
        "rsvp_count": 46,
        "is_paid": true,
        "fee": {
          "amount": "25",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/9db31c92b54d46c4a7e4f34235434b885314e039.jpg",
        "genres": [
          "Breakbeat",
          "Drum & Bass"
        ]
      },
      {
        "id": "2380053",
        "provider": "resident_advisor",
        "title": "blu.2",
        "description": "Lineup: Desiree', Doxia, Gia Genesis, LO-LOW, Melati, Nina Pixina, S3BA, Saroor, Wednesday, WVRM POOL\nGenres: Electronica\nit’s happening \n\n26 artists\n\n3 rooms\n\n10 dj’s \n\n16 hours\n\nblu.2 \n\ntrance space \n\nbe there, be blu\n\n\nblu.2, the second edition of bluparti - a continuation and deepening of the journey we began together.\n\nif this is your first time on blu planet, here is some context about our e",
        "url": "https://ra.co/events/2380053",
        "date_start": "2026-04-11T15:00:00.000",
        "date_end": "2026-04-12T07:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Gaffe",
          "address": "1 Anthony Way, N18 3QT",
          "city": "London",
          "lat": 0,
          "lon": 0
        },
        "organizer": {
          "name": "bluparti"
        },
        "rsvp_count": 398,
        "is_paid": true,
        "fee": {
          "amount": "15-20",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/d60c1b8a927441f693a0378d552c2be5adf93936.jpg",
        "genres": [
          "Electronica"
        ]
      },
      {
        "id": "2414022",
        "provider": "resident_advisor",
        "title": "The South London Soul Train Lounge Special with Jazzheadchronic",
        "description": "Lineup: Jazzheadchronic\nGenres: Disco, Funk / Soul\nIMPROMPTU SOUTH LONDON SOUL TRAIN LOUNGE SPECIAL!! Sat Apr 11 (8pm-1am/Free Entry) - As part of our 15 year anniversary, The South London Soul Train is throwing an Impromptu Free Entry Lounge Special, hosted by SLST founder and your funk, soul, jazz, hop and brass slinging host with the most JAZZHEADCHRONIC deep in the dance at our venue The Clf A",
        "url": "https://ra.co/events/2414022",
        "date_start": "2026-04-11T20:00:00.000",
        "date_end": "2026-04-12T01:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "CLF Art Lounge",
          "address": "G/F, Mountview, 120 Peckham Hill Street, SE15 5JT",
          "city": "London",
          "lat": 0,
          "lon": 0
        },
        "organizer": {
          "name": "Chronic Fonk"
        },
        "rsvp_count": 46,
        "is_paid": true,
        "fee": {
          "amount": "0.0",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/bbe8354aab3bfa6b16af6ed785f4269e5071affb.jpg",
        "genres": [
          "Disco",
          "Funk / Soul"
        ]
      },
      {
        "id": "2363533",
        "provider": "resident_advisor",
        "title": "Groove Room (Latin Minimal Tech All Night Long)",
        "description": "Lineup: Alex Rush, CARSA, Rafa Nandez, Tato (2), TIME LVPSE, William Quintero (2)\nGenres: Tech House, Deep House\nGROOVE ROOM returns to London with a powerful new chapter.\n\nOn Saturday 11th April, we step into a brand new home at the iconic E1 London, taking over the ONYX for a night dedicated to pure underground energy.\n\nE1 has quickly become one of the capital’s most respected electronic music v",
        "url": "https://ra.co/events/2363533",
        "date_start": "2026-04-11T23:00:00.000",
        "date_end": "2026-04-12T05:00:00.000",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "E1",
          "address": "110 Pennington Street, Wapping, London E1W 2BB",
          "city": "London",
          "lat": 51.509058,
          "lon": -0.061664
        },
        "organizer": {
          "name": "E1"
        },
        "rsvp_count": 107,
        "is_paid": true,
        "fee": {
          "amount": "5",
          "currency": "EUR"
        },
        "image_url": "https://images.ra.co/016875a26fc7cdd7d9da7126d6259534437eb6da.png",
        "genres": [
          "Tech House",
          "Deep House"
        ]
      }
    ]
  }
]

export default examples;
