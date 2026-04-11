/**
 * App-store examples for the home skill.
 *
 * Captured from real ImmoScout24/Kleinanzeigen/WG-Gesucht listing search responses, trimmed to 5 listings per query.
 */

export interface HomeSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: HomeSearchStoreExample[] = [
  {
    "id": "store-example-home-search-1",
    "query": "Apartments for rent in Berlin",
    "query_translation_key": "settings.app_store_examples.home.search.1",
    "provider": "Multi",
    "status": "finished",
    "results": [
      {
        "id": "wg_5095231",
        "title": "Zwischenmiete von 25 qm-Zimmer direkt an der Hasenheide in einer 4er-WG",
        "price": 520.0,
        "price_label": "520 EUR/month",
        "size_sqm": 25.0,
        "rooms": 0.0,
        "address": "Karlsgartenstr., 12049 (Neukölln)",
        "image_url": "https://img.wg-gesucht.de/media/up/2026/14/465ffffef9d391e0603f332a31a2bb5400a146b3b376af07d6abe8ba74f57d9b_1000062210.small.jpg",
        "url": "https://www.wg-gesucht.de/wg-zimmer-in-Neukölln.5095231.html",
        "provider": "WG-Gesucht",
        "listing_type": "rent",
        "available_from": "01.05.2026",
        "latitude": 52.52,
        "longitude": 13.405,
        "furnished": true
      },
      {
        "id": "wg_6015095",
        "title": "Friedenau:Praktikant/In; MasterStudent/In,  Zimmer mit eig. Küche und eig. Eingang in ZWECK-WG.",
        "price": 630.0,
        "price_label": "630 EUR/month",
        "size_sqm": 14.0,
        "rooms": 0.0,
        "address": "Dürerplatznähe, 12157 (Friedenau)",
        "image_url": "https://img.wg-gesucht.de/media/up/2021/00/c5d72eaf8886f30fbf23cdb25784ea687cb794138e67b7fe352016fa07cfab50_20201223_110110.small.jpg",
        "url": "https://www.wg-gesucht.de/wg-zimmer-in-Friedenau.6015095.html",
        "provider": "WG-Gesucht",
        "listing_type": "rent",
        "available_from": "01.05.2026",
        "latitude": 52.52,
        "longitude": 13.405,
        "furnished": true
      },
      {
        "id": "wg_9028779",
        "title": "GIRLS WG IN SIMON DACH STR ♥️",
        "price": 690.0,
        "price_label": "690 EUR/month",
        "size_sqm": 12.0,
        "rooms": 0.0,
        "address": "Simon-Dach-Straße, 10245 (Friedrichshain)",
        "image_url": "https://img.wg-gesucht.de/media/up/2026/14/7cf20daa7e115bda50196bf4cd438492e5ff375de3061e252ad9f96f2b6d3dc1_177589507079294671787079250808.small.JPEG",
        "url": "https://www.wg-gesucht.de/wg-zimmer-in-Friedrichshain.9028779.html",
        "provider": "WG-Gesucht",
        "listing_type": "rent",
        "available_from": "01.05.2026",
        "latitude": 52.52,
        "longitude": 13.405,
        "furnished": true
      },
      {
        "id": "ka_3322758386",
        "title": "2-Zimmer-Wohnung in berlin-Spandau zur Miete",
        "price": 720.0,
        "price_label": "720 EUR/month",
        "size_sqm": 57.0,
        "rooms": 2.0,
        "address": "13591 Spandau",
        "image_url": "https://img.kleinanzeigen.de/api/v1/prod-user/images/9f/9f5063c4-ef46-4be6-ac84-63cea3f37613?rule=$_2.JPG",
        "url": "https://www.kleinanzeigen.de/s-anzeige/3322758386",
        "provider": "Kleinanzeigen",
        "listing_type": "rent",
        "latitude": 52.52,
        "longitude": 13.405
      },
      {
        "id": "ka_3379195335",
        "title": "1 Zimmer Wohnung",
        "price": 749.0,
        "price_label": "749 EUR/month",
        "size_sqm": 40.0,
        "rooms": 1.0,
        "address": "13583 Spandau",
        "url": "https://www.kleinanzeigen.de/s-anzeige/3379195335",
        "provider": "Kleinanzeigen",
        "listing_type": "rent",
        "latitude": 52.52,
        "longitude": 13.405
      }
    ]
  },
  {
    "id": "store-example-home-search-2",
    "query": "Apartments to buy in Munich",
    "query_translation_key": "settings.app_store_examples.home.search.2",
    "provider": "Multi",
    "status": "finished",
    "results": [
      {
        "id": "ka_3294483815",
        "title": "Perfekt für Singles oder Kapitalanleger: Moderne 1-Zimmer-Wohnung mit Balkon und TG in Berg-am-Laim",
        "price": 200500.0,
        "price_label": "200.500 EUR",
        "size_sqm": 24.38,
        "rooms": 1.0,
        "address": "81673 Berg-&#8203am-&#8203Laim",
        "image_url": "https://img.kleinanzeigen.de/api/v1/prod-user/images/40/40274884-42d6-4714-b3ce-d5635cb94005?rule=$_2.JPG",
        "url": "https://www.kleinanzeigen.de/s-anzeige/3294483815",
        "provider": "Kleinanzeigen",
        "listing_type": "buy",
        "latitude": 48.137,
        "longitude": 11.576
      },
      {
        "id": "ka_3318028074",
        "title": "Modernisiertes Wohlfühlzuhause mit Balkon und Aufzug- sehr gute Kapitatlanlage oder Eigenheim",
        "price": 495000.0,
        "price_label": "495.000 EUR",
        "size_sqm": 61.7,
        "rooms": 2.0,
        "address": "81927 Bogenhausen",
        "url": "https://www.kleinanzeigen.de/s-anzeige/3318028074",
        "provider": "Kleinanzeigen",
        "listing_type": "buy",
        "latitude": 48.137,
        "longitude": 11.576
      },
      {
        "id": "ka_3243996159",
        "title": "610/ Charmante 2-Zimmer-Wohnung mit Südwestbalkon im 1. OG",
        "price": 553000.0,
        "price_label": "553.000 EUR",
        "size_sqm": 53.2,
        "rooms": 2.0,
        "address": "80993 Moosach",
        "image_url": "https://img.kleinanzeigen.de/api/v1/prod-user/images/46/467b7940-69ea-47e1-a6f2-9a41e2b8ac0c?rule=$_2.JPG",
        "url": "https://www.kleinanzeigen.de/s-anzeige/3243996159",
        "provider": "Kleinanzeigen",
        "listing_type": "buy",
        "latitude": 48.137,
        "longitude": 11.576
      },
      {
        "id": "ka_2415044711",
        "title": "Vermietete Wohnung zur Kapitalanlage",
        "price": 554000.0,
        "price_label": "554.000 EUR",
        "size_sqm": 77.78,
        "rooms": 3.0,
        "address": "80634 Neuhausen",
        "image_url": "https://img.kleinanzeigen.de/api/v1/prod-user/images/f5/f5e767d8-2570-4dd6-81e0-ccbc4605e0d3?rule=$_2.JPG",
        "url": "https://www.kleinanzeigen.de/s-anzeige/2415044711",
        "provider": "Kleinanzeigen",
        "listing_type": "buy",
        "latitude": 48.137,
        "longitude": 11.576
      },
      {
        "id": "ka_3337649326",
        "title": "Obermenzing: Dachterrassenwohnung mit Penthouse-Charakter und Entwicklungsspielraum",
        "price": 590000.0,
        "price_label": "590.000 EUR",
        "size_sqm": 85.34,
        "rooms": 3.0,
        "address": "81247 Allach-&#8203Untermenzing",
        "url": "https://www.kleinanzeigen.de/s-anzeige/3337649326",
        "provider": "Kleinanzeigen",
        "listing_type": "buy",
        "latitude": 48.137,
        "longitude": 11.576
      }
    ]
  },
  {
    "id": "store-example-home-search-3",
    "query": "Homes in Hamburg Altstadt",
    "query_translation_key": "settings.app_store_examples.home.search.3",
    "provider": "Multi",
    "status": "finished",
    "results": []
  }
]

export default examples;
