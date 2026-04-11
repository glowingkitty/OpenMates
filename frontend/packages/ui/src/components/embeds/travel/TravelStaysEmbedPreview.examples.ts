/**
 * App-store examples for the travel skill.
 *
 * Captured from real Google Hotels (SerpAPI) responses, trimmed to 4 stays per query and normalised to the preview.ts field shape.
 */

export interface TravelStaysStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: TravelStaysStoreExample[] = [
  {
    "id": "store-example-travel-search-stays-1",
    "query": "Hotels in Barcelona, Spain",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.1",
    "provider": "Google",
    "status": "finished",
    "results": [
      {
        "name": "Novotel Barcelona City",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.4,
        "reviews": 7631,
        "currency": "EUR",
        "amenities": [
          "Breakfast ($)",
          "Free Wi-Fi",
          "Parking ($)",
          "Outdoor pool",
          "Air conditioning",
          "Pet-friendly",
          "Fitness center",
          "Bar"
        ],
        "description": "Modern rooms & suites in a polished property with a refined restaurant & a seasonal rooftop pool.",
        "link": "https://all.accor.com/lien_externe.svlt?goto=fiche_hotel&code_hotel=5560&merchantid=seo-maps-ES-5560&sourceid=aw-cen&utm_medium=seo%20maps&utm_source=google%20Maps&utm_campaign=seo%20maps",
        "latitude": 41.4038398,
        "longitude": 2.1911943,
        "check_in_time": "2:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh6.googleusercontent.com/proxy/gr1Vvc-qb0iEbMIGow1Q_UR_F9CVti9JiblxedGdX2nAGRSzWs_OrgmelQY69RLqUPWXVXcVrq6s-3IbtTvHRPvNEzXiZSvjAwB5R_opFw9wL-jbBGEaBYgcerkm1l19kpWZ_VCvyr9aLCr8jFS4lahTp93OH-y_LJT7V_38sQ=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "Hotel Soho Barcelona",
        "property_type": "hotel",
        "hotel_class": 3,
        "overall_rating": 4.6,
        "reviews": 1426,
        "currency": "EUR",
        "rate_per_night": "€205",
        "extracted_rate_per_night": 205,
        "total_rate": "€616",
        "amenities": [
          "Breakfast",
          "Free Wi-Fi",
          "Parking",
          "Outdoor pool",
          "Air conditioning",
          "Restaurant",
          "Full-service laundry",
          "Accessible"
        ],
        "description": "Sleek rooms in a trendy hotel with free Wi-Fi, plus a lounge, a terrace & a rooftop pool.",
        "link": "http://www.hotelsohobarcelona.com/",
        "latitude": 41.3834388,
        "longitude": 2.1598504,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/proxy/fsS4suPxI9HP3anWZWxcXg6-Qx9VdUBI9-EkDL_4z65djraREscHhs5P7x15JGFBSa9aho0uxPWJm7AGye7iskw0PH-PdKYILF9aIGnuWQjvtbBqexHFVf-Qe3eXeSA2fyTg787woBZlyC94FTIRwGU5HWBkL6o8Syg8X2f-eA=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "Sercotel Ámister Art Hotel",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.3,
        "reviews": 2170,
        "currency": "EUR",
        "rate_per_night": "€232",
        "extracted_rate_per_night": 232,
        "total_rate": "€695",
        "amenities": [
          "Breakfast ($)",
          "Free Wi-Fi",
          "Parking ($)",
          "Outdoor pool",
          "Air conditioning",
          "Pet-friendly",
          "Fitness center",
          "Full-service laundry"
        ],
        "description": "Bright rooms & suites in a contemporary hotel featuring a rooftop pool & a stylish bar.",
        "link": "https://www.sercotelhoteles.com/es/hotel-amister-art-hotel?utm_source=google&utm_medium=referral&utm_campaign=metasearch-links",
        "latitude": 41.384344999999996,
        "longitude": 2.151522,
        "check_in_time": "2:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/APNQkAEIi7imu8kBwi5PbUTdz-Lt2H2RuuQ7aq3bB0UFUlJj8MFA0VtYw4B3eYewbT1gaJQVJBuyuJri3KboY5bQgxaai8hoi_ljoO87dsZzj5qTUdlv3m6U8Po0lkRpynWBwhiwNFyq3r9qEShG=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "Majestic Hotel & Spa Barcelona",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.6,
        "reviews": 5548,
        "currency": "EUR",
        "rate_per_night": "€555",
        "extracted_rate_per_night": 555,
        "total_rate": "€1,666",
        "amenities": [
          "Breakfast ($)",
          "Free Wi-Fi",
          "Parking ($)",
          "Outdoor pool",
          "Air conditioning",
          "Pet-friendly",
          "Fitness center",
          "Spa"
        ],
        "description": "Grand, storied hotel featuring a sophisticated restaurant, bars & a spa, plus a rooftop pool.",
        "link": "https://www.hotelmajestic.es/",
        "latitude": 41.3934401,
        "longitude": 2.1639871,
        "check_in_time": "3:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/APNQkAFFMIjwQ9B6RbU-Xvh_gnswqFxpGcZdfc-pvgy_4kxZ8zzMfZA28XtDzpeAwxDmVt3EI_uK8yohHeTZ-b1dEqQ_378pQs-yiKCXSlUUBoi1OKg-gEMXNK9Q8ay86ZXXgF-f624S=s287-w287-h192-n-k-no-v1"
          }
        ]
      }
    ]
  },
  {
    "id": "store-example-travel-search-stays-2",
    "query": "Boutique hotels in Paris, France",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.2",
    "provider": "Google",
    "status": "finished",
    "results": [
      {
        "name": "Studio Porte de Paris",
        "property_type": "vacation rental",
        "currency": "EUR",
        "rate_per_night": "€149",
        "extracted_rate_per_night": 149,
        "total_rate": "€448",
        "amenities": [
          "Heating",
          "Kitchen",
          "Microwave",
          "Oven stove",
          "Smoke-free",
          "Free Wi-Fi"
        ],
        "latitude": 48.85846710205078,
        "longitude": 2.4184000492095947,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/proxy/sIqsTWEJaJoiuHIVsCJCIGXFWnrgvUTqnGCKY6LZpfJyh_2PFRxrXdI1xmIOR3j0D89qpd7DbH1lFb92KiYuWWqlE8MpeOMb6piPIBuxdiIML9TGnnMNbj5jxma2evi8aaihCB6LsGDZfDWoINXC-F-NQsOwyg=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "Romantic Studio Marais Historical Center Paris",
        "property_type": "vacation rental",
        "overall_rating": 4.6,
        "reviews": 94,
        "currency": "EUR",
        "rate_per_night": "€183",
        "extracted_rate_per_night": 183,
        "total_rate": "€550",
        "amenities": [
          "Heating",
          "Kitchen",
          "Oven stove",
          "Smoke-free",
          "Free Wi-Fi"
        ],
        "latitude": 48.86141586303711,
        "longitude": 2.3627989292144775,
        "check_in_time": "3:00 PM",
        "check_out_time": "5:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/proxy/AMGyOdZkD0U7CdKstjuag6pjCCBQH2u_LgxenHKRBPwxJnspjUnuyvKPlWkw34MYUBryDOEbqk3X_263uiFkGo4cCV7bDCj3oax9Vl0M5quAoAmliUT4IqbQG-hKslsBWPiVjFNv_grR0nbc4LcR-4VY6AZZmA=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "French Theory",
        "property_type": "hotel",
        "hotel_class": 3,
        "currency": "EUR",
        "rate_per_night": "€184",
        "extracted_rate_per_night": 184,
        "total_rate": "€551",
        "amenities": [
          "Breakfast ($)",
          "Free Wi-Fi",
          "Air conditioning",
          "Pet-friendly",
          "Bar",
          "Restaurant",
          "Airport shuttle",
          "Full-service laundry"
        ],
        "description": "Boutique hotel in an 18th-century building, with a cafe, music studio & gift shop.",
        "link": "https://frenchtheory.com/",
        "latitude": 48.8480821,
        "longitude": 2.3422372,
        "check_in_time": "3:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/AHVAweo75f5HAul9wwEk5ARPz-rY1BIl9G64uc1bh5evThtfuUIzjSog_t1B_ibvwoR9oXDjbaMwEE2RDJBQUE5D0Y4Nh9-6MHwdohPyXX82wHs4UwBKMTPmZnfVQyrFXZmcMyq1LUhoSA=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "Hôtel De Varenne",
        "property_type": "hotel",
        "hotel_class": 4,
        "currency": "EUR",
        "rate_per_night": "€213",
        "extracted_rate_per_night": 213,
        "total_rate": "€638",
        "amenities": [
          "Breakfast ($)",
          "Free Wi-Fi",
          "Parking ($)",
          "Air conditioning",
          "Bar",
          "Room service",
          "Airport shuttle",
          "Accessible"
        ],
        "description": "Classy rooms & suites in a 19th-century building with a wood-paneled lounge & a courtyard terrace.",
        "link": "http://www.hoteldevarenne.com/",
        "latitude": 48.8570084,
        "longitude": 2.3172318,
        "check_in_time": "3:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/AHVAweq8KxZohGi6KFdT4ea5wGcwR-PTKdZLh6HMTtVFOwm60U2Y3v7Je3-cgUPgU_SsF4BsHK-Ml2wkFHhbzkgwmQMQ1NTppRXNNsQT1upOhEmok4LEe1LwGI3YOahopnit6CcFC3HA6w=s287-w287-h192-n-k-no-v1"
          }
        ]
      }
    ]
  },
  {
    "id": "store-example-travel-search-stays-3",
    "query": "Beach resorts in Bali, Indonesia",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.3",
    "provider": "Google",
    "status": "finished",
    "results": [
      {
        "name": "The Anvaya Beach Resort Bali",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.7,
        "reviews": 14327,
        "currency": "EUR",
        "rate_per_night": "€114",
        "extracted_rate_per_night": 114,
        "total_rate": "€569",
        "amenities": [
          "Free breakfast",
          "Free Wi-Fi",
          "Free parking",
          "Outdoor pool",
          "Air conditioning",
          "Fitness center",
          "Spa",
          "Beach access"
        ],
        "description": "Sophisticated resort offering 8 pools, 2 restaurants & a spa, plus a private beach & a kids' club.",
        "link": "https://www.theanvayabali.com/",
        "latitude": -8.732239700000001,
        "longitude": 115.16591190000001,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/AHVAweqYQ_H1PVvPrIL7xcndzj_VahliOcAAfNHxktu7Ftx-697nAct57pWGzRR-qdEUEUvZV04l_Cydsk4CpswATsFiOQGQxo6AjJrYMSWqVY7wCB2dP-kbEpcO31SGbPPuAFWtrsA=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "The Ritz-Carlton, Bali",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.6,
        "reviews": 4345,
        "currency": "EUR",
        "rate_per_night": "€371",
        "extracted_rate_per_night": 371,
        "total_rate": "€1,854",
        "amenities": [
          "Breakfast ($)",
          "Free Wi-Fi",
          "Free parking",
          "Pools",
          "Hot tub",
          "Air conditioning",
          "Fitness center",
          "Spa"
        ],
        "description": "Zen-like quarters, some with butler service, in an upscale property offering refined dining & a spa.",
        "link": "https://www.ritzcarlton.com/en/hotels/dpssw-the-ritz-carlton-bali/overview/?cid=NAT_google_hotel_url",
        "latitude": -8.8306709,
        "longitude": 115.2153312,
        "check_in_time": "3:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/AHVAweoaEgf28jEfyeyQ3JBQO9hIlRX-606ll02qCN0d1bvC0_ocUJE6B6jGH2PHhqbIg3rutTsCsorDKg1mldmD8qfQC2U3xEZ-a7_14XrEghXlOvRpURSPvMcrwiFVGyKrz4EfiIQS9pc9Obqv=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "The Seminyak Beach Resort & Spa",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.8,
        "reviews": 2703,
        "currency": "EUR",
        "rate_per_night": "€223",
        "extracted_rate_per_night": 223,
        "total_rate": "€1,113",
        "amenities": [
          "Breakfast",
          "Free Wi-Fi",
          "Free parking",
          "Outdoor pool",
          "Hot tub",
          "Air conditioning",
          "Fitness center",
          "Spa"
        ],
        "description": "High-end quarters on a seafront resort with multiple restaurants, plus an outdoor pool & a spa.",
        "link": "http://www.theseminyak.com/",
        "latitude": -8.686074699999999,
        "longitude": 115.15422779999999,
        "check_in_time": "2:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/AHVAwep8P2VyUhZmPKrx2v-aadP84N1-c4DiT0SyBigC4mXY9yEz8zlLLp3oe6l8V6EbbGkKnkAEYIikA4ltJhNbm24R41Wt65Sr8Vhr0Yw8_qLLoFbzUrtKVf3O1KUmvR7MAIR_YnBRpg=s287-w287-h192-n-k-no-v1"
          }
        ]
      },
      {
        "name": "Hotel Indigo Bali Seminyak Beach by IHG",
        "property_type": "hotel",
        "hotel_class": 5,
        "currency": "EUR",
        "rate_per_night": "€237",
        "extracted_rate_per_night": 237,
        "total_rate": "€1,183",
        "amenities": [
          "Breakfast ($)",
          "Free Wi-Fi",
          "Free parking",
          "Outdoor pool",
          "Hot tub",
          "Air conditioning",
          "Fitness center",
          "Spa"
        ],
        "description": "Polished rooms, suites & villas in an haute beachfront hotel with an outdoor pool, a spa & a gym.",
        "link": "https://www.ihg.com/hotelindigo/hotels/us/en/bali/dpsin/hoteldetail?cm_mmc=GoogleMaps-_-IN-_-ID-_-DPSIN",
        "latitude": -8.695094,
        "longitude": 115.16236699999999,
        "check_in_time": "3:00 PM",
        "check_out_time": "12:00 PM",
        "images": [
          {
            "thumbnail": "https://lh3.googleusercontent.com/gps-cs-s/AHVAwerlM3Y_nJmc-32IqAaCP5l6-9iZwpUYz3MVi4m2j1vbm-pkyGG0dSHwF7QX-fZP1hiuqzNg3AXsmM_MOyNGfnb-WWi261_IPtp1ybkqNExkigzkY40xDK0_-iJG0wiaEtSAiAZw=s287-w287-h192-n-k-no-v1"
          }
        ]
      }
    ]
  }
]

export default examples;
