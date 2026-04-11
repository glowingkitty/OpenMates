/**
 * App-store examples for the maps/search skill.
 *
 * Captured from real Google Maps Places API responses, field-mapped to the PlaceResult shape the preview/fullscreen components expect (displayName, formattedAddress, userRatingCount, ...).
 *
 * Each example includes an optional `query_translation_key` that
 * SkillExamplesSection resolves via the i18n store at render time, so
 * the card label is localised while the raw provider data stays
 * authentic.
 */

export interface MapsSearchStoreExample {
  id: string;
  query: string;
  query_translation_key: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: MapsSearchStoreExample[] = [
  {
    "id": "store-example-maps-search-1",
    "query": "best coffee shops in San Francisco",
    "query_translation_key": "app_store_examples.maps.search.1",
    "provider": "Google Maps",
    "status": "finished",
    "results": [
      {
        "displayName": "The Coffee Movement",
        "formattedAddress": "1737 Balboa St, San Francisco, CA 94121, USA",
        "location": {
          "latitude": 37.7764721,
          "longitude": -122.47782249999999
        },
        "rating": 4.8,
        "userRatingCount": 558,
        "websiteUri": "https://www.thecoffeemovement.com/",
        "placeId": "ChIJTfb1d_uHhYARRpn5d_Fk1SU",
        "placeType": "coffee_shop",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNGiLiLSW8-1FEaW45_a1KowsOQBCaUh3G0ELcnTO_VvMXICFgPmWWJWvuPH2Xe5MzYcz0gN2H34cHj7Wx7CtMlEtEjpAzTtEZfscNHGfADweOiame_82wfGO6Mtdp2labFtIEFxW7TkMIGjYCyzlSG6AQ=s4800-w1200"
      },
      {
        "displayName": "The Coffee Berry SF",
        "formattedAddress": "1410 Lombard St, San Francisco, CA 94123, USA",
        "location": {
          "latitude": 37.8014124,
          "longitude": -122.4249979
        },
        "rating": 4.9,
        "userRatingCount": 556,
        "websiteUri": "http://thecoffeeberrysf.com/",
        "placeId": "ChIJC2jb8DWBhYARo4AAX78U50c",
        "placeType": "coffee_shop",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNENEvaLCQVxXBfFtNPnatTGfeKQTD19wptxIqlODFQGketopx6nC-ogDh83Xpq4N-4372rv6YNloCkyi5gOYkhxs1FMmOO7T43AiuwwkdfyUX2Wjy8K4kvTu_IVqumd8Hp3UfFxZYfwz3q0kbyhDoQx=s4800-w1200"
      },
      {
        "displayName": "Doppio Coffee & Brunch",
        "formattedAddress": "1551 Mission St, San Francisco, CA 94103, USA",
        "location": {
          "latitude": 37.7733151,
          "longitude": -122.41801260000001
        },
        "rating": 4.9,
        "userRatingCount": 373,
        "websiteUri": "https://doppiosf.com/",
        "placeId": "ChIJy8vmGC2BhYARu919i3bko-Q",
        "placeType": "coffee_shop",
        "imageUrl": "https://lh3.googleusercontent.com/places/ANXAkqGjj38uo182dYRFY9owzZ8BW1rjXp9YP-MHWJZS34NsWSIVUYDxoasCLNCamBfayKoeda8IMZLCLSqMSWxIh40Ky4GqpJP6jZc=s4800-w384"
      },
      {
        "displayName": "Delah Coffee",
        "formattedAddress": "370 4th St, San Francisco, CA 94107, USA",
        "location": {
          "latitude": 37.7810165,
          "longitude": -122.40022440000001
        },
        "rating": 4.7,
        "userRatingCount": 1094,
        "websiteUri": "https://delahcoffee.com/order-online/",
        "placeId": "ChIJL86gDJmBhYARjQPJ6NsYQZQ",
        "placeType": "coffee_shop",
        "imageUrl": "https://lh3.googleusercontent.com/places/ANXAkqF9ffxk42x5vhujMJIg7MSvUDjvUqNEDS2LJqRowiIr5m6H24ASWiVwSmrgul_anWG7CJ-7VW21KgawoE13bScqm-4AS-2TVLQ=s4800-w1200"
      },
      {
        "displayName": "Saint Frank Coffee",
        "formattedAddress": "2340 Polk St, San Francisco, CA 94109, USA",
        "location": {
          "latitude": 37.7984797,
          "longitude": -122.4220775
        },
        "rating": 4.5,
        "userRatingCount": 1354,
        "websiteUri": "http://www.saintfrankcoffee.com/",
        "placeId": "ChIJmfgIQ-iAhYARq5osc-JybBo",
        "placeType": "coffee_shop",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNHX2n5tmtnR3IrqSpRD116UM-6r91Z-p9PYx6rvAoxE9jV1CDqWiokwuoE8nNuDDmrQp--B_XKkCo5O_N2zgeJOYDvC20n5bVuEyWGHUVokGNCIRm1vjx_uXsxqCBSHcaMFridepqXNCkrrvQ=s4800-w1200"
      }
    ]
  },
  {
    "id": "store-example-maps-search-2",
    "query": "italian restaurants near Times Square New York",
    "query_translation_key": "app_store_examples.maps.search.2",
    "provider": "Google Maps",
    "status": "finished",
    "results": [
      {
        "displayName": "Carmine's - Time Square",
        "formattedAddress": "200 W 44th St, New York, NY 10036, USA",
        "location": {
          "latitude": 40.757498,
          "longitude": -73.986654
        },
        "rating": 4.5,
        "userRatingCount": 18718,
        "websiteUri": "https://carminesnyc.com/locations/times-square",
        "placeId": "ChIJR9So-lRYwokRX1xEjA0rChA",
        "placeType": "italian_restaurant",
        "imageUrl": "https://lh3.googleusercontent.com/places/ANXAkqF0YY427U1donlRh7i63itkRPrCX92I2ThChr9E7F_d70y6_9jr519EkJOglsCRQgs-isKMZlbcjLAtxIyrpDeI7oPypZJZjUM=s4800-w1200"
      },
      {
        "displayName": "Tony's Di Napoli",
        "formattedAddress": "147 W 43rd St, New York, NY 10036, USA",
        "location": {
          "latitude": 40.756484199999996,
          "longitude": -73.9853808
        },
        "rating": 4.6,
        "userRatingCount": 8157,
        "websiteUri": "https://www.tonysnyc.com/",
        "placeId": "ChIJVS2qI1VYwokRFo18YsKvHYM",
        "placeType": "italian_restaurant",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNGF5vhPwI3QE9zslWz3-hen2RJgD3Id6Bb2550xPHw3WICgRwK0VKE-AOJwp_jXvUKNSQd77h1oAqHslemScY6cTvBbOE_CkM2Fz4j2uWYLy306t8Iqeb415qdcrzRNfneTJeo9fIXtLNO6nw=s4800-w1200"
      },
      {
        "displayName": "Osteria La Baia",
        "formattedAddress": "129 W 52nd St, New York, NY 10019, USA",
        "location": {
          "latitude": 40.7618881,
          "longitude": -73.9809702
        },
        "rating": 4.9,
        "userRatingCount": 5332,
        "websiteUri": "https://www.labaianyc.com/?y_source=1_MTAwNTA2Mjg0My03MTUtbG9jYXRpb24ud2Vic2l0ZQ%3D%3D",
        "placeId": "ChIJo9FTvDBZwokRFAZ0i4jbLuk",
        "placeType": "italian_restaurant",
        "imageUrl": "https://lh3.googleusercontent.com/places/ANXAkqFtomH8Nw4nbiE4A92gxatin_HuLXnawkBRAW5MjSEhBxVocR6wokUoIcncjzaEDiFMdSsuTEEIrUMIQHMU2ZFT9gF20L-Kb5s=s4800-w1200"
      },
      {
        "displayName": "Trattoria Trecolori",
        "formattedAddress": "254 W 47th St, New York, NY 10036, USA",
        "location": {
          "latitude": 40.7599972,
          "longitude": -73.9867421
        },
        "rating": 4.5,
        "userRatingCount": 2890,
        "websiteUri": "http://www.trattoriatrecolori.com/",
        "placeId": "ChIJYepwLVRYwokRsvXclA3XFqo",
        "placeType": "italian_restaurant",
        "imageUrl": "https://lh3.googleusercontent.com/places/ANXAkqFAAWIxH7xmuCeJSmLKYSHmkKf67Je33txdS82O9PRVRYIsyK7B-0Xvma_LRL8Lufhi9Ofaa3NV4xEk4gSGuhLUnwd3MLPQbGc=s4800-w1200"
      },
      {
        "displayName": "La Pecora Bianca Bryant Park",
        "formattedAddress": "20 W 40th St, New York, NY 10018, USA",
        "location": {
          "latitude": 40.7525176,
          "longitude": -73.9831529
        },
        "rating": 4.8,
        "userRatingCount": 6947,
        "websiteUri": "https://www.lapecorabianca.com/",
        "placeId": "ChIJKykw-aZZwokRW7K0ykZUxNo",
        "placeType": "italian_restaurant",
        "imageUrl": "https://lh3.googleusercontent.com/places/ANXAkqEohJz4lfJc1VCOghxSVSrYRWilD4UlZp5DMkvOMp2hSBjY2BkqyywEPuYDF6nf6LxcKjvgdgV35T9NBoHcKukElxGmtCe-KQk=s4800-w1200"
      }
    ]
  },
  {
    "id": "store-example-maps-search-3",
    "query": "bookstores in central London",
    "query_translation_key": "app_store_examples.maps.search.3",
    "provider": "Google Maps",
    "status": "finished",
    "results": [
      {
        "displayName": "Foyles",
        "formattedAddress": "107 Charing Cross Rd, London WC2H 0EB, UK",
        "location": {
          "latitude": 51.5143097,
          "longitude": -0.1298993
        },
        "rating": 4.7,
        "userRatingCount": 13215,
        "websiteUri": "http://www.foyles.co.uk/",
        "placeId": "ChIJ5574rdIEdkgRA9294QpXDhw",
        "placeType": "book_store",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNGmQYefoWs7hwyXNX4JtHM3LlwA783AC8VemGVLj7MG6cUeHUAwDXFzfZzT6NV-SOxSRSGwC7pVLUD0Xo8TeeOEmmvEvehgDR4MiLNYHds-72zsvz1yegr7T-YgfXedh2nxjE2qd7HbxkDRGWg=s4800-w1200"
      },
      {
        "displayName": "Daunt Books Marylebone",
        "formattedAddress": "84 Marylebone High St, London W1U 4QW, UK",
        "location": {
          "latitude": 51.5204015,
          "longitude": -0.15199169999999998
        },
        "rating": 4.8,
        "userRatingCount": 6625,
        "websiteUri": "https://www.dauntbooks.co.uk/",
        "placeId": "ChIJTQJH99EadkgRgli4gpxCkOY",
        "placeType": "book_store",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNE3cI2gw5MLV-1rr3g2f6lG_UjXXi5cZ8DPiL-A6P1EaAJqreiTq9UluOF6rcRflSfl14LG5u9CMH3Z1RWNnjIPmTce9Ph9u1-p_GScLO4u-qo2gVCR3gIx1wcgntZIikpEB-9gM4cVtz1-Kw=s4800-w1200"
      },
      {
        "displayName": "Waterstones",
        "formattedAddress": "203-206 Piccadilly, London W1J 9HD, UK",
        "location": {
          "latitude": 51.509125,
          "longitude": -0.136048
        },
        "rating": 4.7,
        "userRatingCount": 13179,
        "websiteUri": "https://www.waterstones.com/bookshops/piccadilly",
        "placeId": "ChIJHXK0sdYEdkgRcrN_uxt5bOM",
        "placeType": "book_store",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNHTlKIg8QtLVnwn4PAG--UZx-B4bRn21DfKp4tsM1bnWpUToOT3QMhZACKsFvCFhAnXMUwn4uYH1xEGG8AKQYhowTdWzP-NP_c9B3Y37yniUNywXbR4IZFyrSDVFvfcvm8AZIODEj_8-0_ePg=s4800-w1200"
      },
      {
        "displayName": "London Review Bookshop",
        "formattedAddress": "14-16 Bury Pl, London WC1A 2JL, UK",
        "location": {
          "latitude": 51.51851130000001,
          "longitude": -0.12425599999999999
        },
        "rating": 4.7,
        "userRatingCount": 970,
        "websiteUri": "http://www.londonreviewbookshop.co.uk/",
        "placeId": "ChIJY_R5kTMbdkgR_0BYHU9oG84",
        "placeType": "book_store",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNH7f9X9fdoQEL3f3AcKQMSK6O7MFGqrEVZN98wzgkLr5c4EjGtSd0uUNpqJxHMZF2YpEZEUlNb5Q4SaI8DLOia_3qyDO4PlKdHSjZKpO9zQX3aDxUsl0eY6b_QMiCfyVM6AJ5D7MtQD_iWVodE=s4800-w1200"
      },
      {
        "displayName": "Word On The Water - The London Bookbarge",
        "formattedAddress": "Regent's Canal Towpath, London N1C 4LW, UK",
        "location": {
          "latitude": 51.535412,
          "longitude": -0.12347949999999998
        },
        "rating": 4.8,
        "userRatingCount": 1422,
        "websiteUri": "https://www.wordonthewater.co.uk/",
        "placeId": "ChIJ16mQBD4bdkgRQ8z5iJUz9fo",
        "placeType": "book_store",
        "imageUrl": "https://lh3.googleusercontent.com/place-photos/AL8-SNFqHnH8RLfhQWKliRHACmJ7igg0bmujnzedi49ZPFc8N27H7GjDKghblOiOc1vOuFMUbT55VKJfuAibmGxq1MWMrjkEPG4pYhgVQ500BEIPIAKNJnpz2yztSPUs-QAQETXKuPHQkYtkaznHzg=s4800-w1200"
      }
    ]
  }
]

export default examples;
