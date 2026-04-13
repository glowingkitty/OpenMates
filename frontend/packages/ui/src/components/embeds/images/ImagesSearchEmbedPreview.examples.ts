/**
 * App-store examples for the images skill.
 *
 * Captured from real Brave image search. Includes one Artemis II space-mission example plus two everyday lifestyle queries.
 */

export interface ImagesSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
  url?: string;
}

const examples: ImagesSearchStoreExample[] = [
  {
    "id": "store-example-images-search-1",
    "query": "Artemis II mission",
    "query_translation_key": "settings.app_store_examples.images.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "At 12:40 p.m. EST, Dec. 11, 2022, NASA’s Orion spacecraft for the Artemis I mission splashed down in the Pacific Ocean after a 25.5 day mission to the Moon",
        "source_page_url": "https://www.space.com/space-exploration/artemis/artemis-2-moon-astronauts-splashdown-what-to-expect-reentry-landing-timeline",
        "image_url": "https://cdn.mos.cms.futurecdn.net/2NrqVWr8P5MiANHpgRsdh8.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/jmRnMoUhSHfPgE01gyxquQwj08Xe0haI7Bze6gcUji8/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0LzJO/cnFWV3I4UDVNaUFO/SHBnUnNkaDguanBn",
        "source": "space.com",
        "favicon_url": "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
      },
      {
        "title": "The Artemis II mission crew in the Orion spacecraft",
        "source_page_url": "https://www.bbc.com/news/articles/ce8jzr423p9o",
        "image_url": "https://ichef.bbci.co.uk/news/480/cpsprodpb/ca4a/live/ae932730-3430-11f1-a207-8b959fccb503.jpg.webp",
        "thumbnail_url": "https://imgs.search.brave.com/cMID9fZoKueMH5yWJxdax5gWSAKxcqwCz9_AuxbK8DI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pY2hl/Zi5iYmNpLmNvLnVr/L25ld3MvNDgwL2Nw/c3Byb2RwYi9jYTRh/L2xpdmUvYWU5MzI3/MzAtMzQzMC0xMWYx/LWEyMDctOGI5NTlm/Y2NiNTAzLmpwZy53/ZWJw",
        "source": "bbc.com",
        "favicon_url": "https://imgs.search.brave.com/-9uoAONEhH31ac708C2NinDM9OjKbNcruJo3O1baQTM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTljMGQ4ZTFj/YzcwNTIyYTU4ZDk4/ZTg5NTQ0NGQyYjQy/NzU3NTMxNDRjZGFi/NjFkMmRiNGE1MGE5/ZDhhOWMyZS93d3cu/YmJjLmNvbS8"
      },
      {
        "title": "Artemis 2 astronauts work inside the Orion spacecraft on Flight Day 3 of the mission on April 3, 2026.",
        "source_page_url": "https://www.space.com/news/live/artemis-2-nasa-moon-mission-updates-april-10-2026",
        "image_url": "https://cdn.mos.cms.futurecdn.net/D3A5oPJ4pnswpvQUveXKYB.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/M9kdaoqKupfeyyGhpEMWc41IieQh-FeLPqxz0svlNlw/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L0Qz/QTVvUEo0cG5zd3B2/UVV2ZVhLWUIuanBn",
        "source": "space.com",
        "favicon_url": "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
      },
      {
        "title": "The finished Orion spacecraft for the Artemis II mission was officially handed over to NASA for launch processing on May 1, 2025 for a crewed mission to the Moon early next year.",
        "source_page_url": "https://news.lockheedmartin.com/2025-05-01-Lockheed-Martin-Completes-Orion-Development-for-Artemis-II-Mission-to-the-Moon",
        "image_url": "https://mma.prnewswire.com/media/2678180/Lockheed_Martin_Orion_Artemis_II.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/1ER9FN4zbwFgzFDFi8ADN_--ZmvGOti5J26WSz1II4o/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tbWEu/cHJuZXdzd2lyZS5j/b20vbWVkaWEvMjY3/ODE4MC9Mb2NraGVl/ZF9NYXJ0aW5fT3Jp/b25fQXJ0ZW1pc19J/SS5qcGc",
        "source": "news.lockheedmartin.com",
        "favicon_url": "https://imgs.search.brave.com/x9jpU9Y7f5_aDutSAKQwucKRhXb49Ixh2s8RA7IqiBE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNWE5Y2FiM2Rm/YWIxNzc2NWNkNGEz/ZmRiMjcxY2UwMjIx/MzMwOThhYjcwZDNh/YWU2NDRmNjA2ZmE4/YTQzYTdiMy9uZXdz/LmxvY2toZWVkbWFy/dGluLmNvbS8"
      }
    ]
  },
  {
    "id": "store-example-images-search-2",
    "query": "Mediterranean coast village at sunset",
    "query_translation_key": "settings.app_store_examples.images.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Antibes Juan les Pins Mediterranean Sea Coast during twilight, blue hour sunset",
        "source_page_url": "https://dreamstime.com/photos-images/mediterranean-coast-city.html",
        "image_url": "https://thumbs.dreamstime.com/b/antibes-juan-les-pins-mediterranean-sea-coast-twilight-blue-hour-sunset-water-sky-landscape-azur-riviera-cote-d-france-105938581.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/jLGmwMR3XFcbcEhbPzaVRNm5d9zxwS5NNKjSCeXe978/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly90aHVt/YnMuZHJlYW1zdGlt/ZS5jb20vYi9hbnRp/YmVzLWp1YW4tbGVz/LXBpbnMtbWVkaXRl/cnJhbmVhbi1zZWEt/Y29hc3QtdHdpbGln/aHQtYmx1ZS1ob3Vy/LXN1bnNldC13YXRl/ci1za3ktbGFuZHNj/YXBlLWF6dXItcml2/aWVyYS1jb3RlLWQt/ZnJhbmNlLTEwNTkz/ODU4MS5qcGc",
        "source": "dreamstime.com",
        "favicon_url": "https://imgs.search.brave.com/kI5ez8fDXyb9W59MbgBlMQXmM3OO2oHpiq9hM3348g8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDVmNDBkMDZi/NmI5Zjc3NTM5YmM3/OTU0YWU0MzNkNjk3/Yzk2NGE0MTM0Njc2/YmUwYmMzZDk4NjJm/NjVkNzliZi9kcmVh/bXN0aW1lLmNvbS8"
      },
      {
        "title": "historic village of bonifacio, corsica, france - mediterranean-sunset stock pictures, royalty-free photos & images",
        "source_page_url": "https://gettyimages.com/photos/mediterranean-sea-sunset?page=3",
        "image_url": "https://media.gettyimages.com/id/2220705311/photo/historic-village-of-bonifacio-corsica-france.jpg?s=612x612&w=0&k=20&c=hKWSYU-_xJIugkE3d_3Ww_5Tc3dLEuKQMlbt18QH2y0=",
        "thumbnail_url": "https://imgs.search.brave.com/73qXkQyaU3lhYqBk-YIcnSNyz0ikiPiGyMeyKjPP-m0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5nZXR0eWltYWdl/cy5jb20vaWQvMjIy/MDcwNTMxMS9waG90/by9oaXN0b3JpYy12/aWxsYWdlLW9mLWJv/bmlmYWNpby1jb3Jz/aWNhLWZyYW5jZS5q/cGc_cz02MTJ4NjEy/Jnc9MCZrPTIwJmM9/aEtXU1lVLV94Skl1/Z2tFM2RfM1d3XzVU/YzNkTEV1S1FNbGJ0/MThRSDJ5MD0",
        "source": "gettyimages.com",
        "favicon_url": "https://imgs.search.brave.com/4vLg_GlfuZTnIziJ0Q3FNyfG6gQxf8DmM1nxb-fhCwM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMWFmMTM1NDY2/YTFmZTAwYjIxY2Yx/YzIwNTAxYTZkYzAz/YmQ0ZjBkNGYxYzZm/NGNhNWM0NGIzMDk2/MzAzMTRhMS9nZXR0/eWltYWdlcy5jb20v"
      },
      {
        "title": "Italian Coastline Church Print Mediterranean Sunset Art Coastal Town Seascape Pastel Sky Wall Decor",
        "source_page_url": "https://www.etsy.com/market/mediterranean_sunset",
        "image_url": "https://i.etsystatic.com/50196019/r/il/da62e1/5858597418/il_600x600.5858597418_o9v8.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/cQXqybbAK-Iy0PVRdfaHArZXqQVPQxV-gmXdyzdusn8/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pLmV0/c3lzdGF0aWMuY29t/LzUwMTk2MDE5L3Iv/aWwvZGE2MmUxLzU4/NTg1OTc0MTgvaWxf/NjAweDYwMC41ODU4/NTk3NDE4X285djgu/anBn",
        "source": "etsy.com",
        "favicon_url": "https://imgs.search.brave.com/VV6KUN1qWhB24EKDo1dIESK_1GyC0VpfAFwGmI97i6w/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjcwZDg1MmI2/YTMzN2YwMThkMzVj/YmIwZmU4YTcwMTA3/ZjZhYzAzNGFmNjBm/NmZjNTVhNWNmNmFh/Zjc4MmMxZi93d3cu/ZXRzeS5jb20v"
      },
      {
        "title": "Mediterranean Sunset Painting Print, Tropical Bedroom Decor, Beach Home Art, Village Life Painting Print, Exotic House Ideas,Sunset Wall Art",
        "source_page_url": "https://www.etsy.com/market/mediterranean_sunset",
        "image_url": "https://i.etsystatic.com/28984245/c/1906/1906/146/0/il/c2e99e/4085529933/il_600x600.4085529933_232e.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/zVVKLBlMrbrTbeyNusZHIR-M65sDZ2dzDv88yfr0I0Y/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pLmV0/c3lzdGF0aWMuY29t/LzI4OTg0MjQ1L2Mv/MTkwNi8xOTA2LzE0/Ni8wL2lsL2MyZTk5/ZS80MDg1NTI5OTMz/L2lsXzYwMHg2MDAu/NDA4NTUyOTkzM18y/MzJlLmpwZw",
        "source": "etsy.com",
        "favicon_url": "https://imgs.search.brave.com/VV6KUN1qWhB24EKDo1dIESK_1GyC0VpfAFwGmI97i6w/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjcwZDg1MmI2/YTMzN2YwMThkMzVj/YmIwZmU4YTcwMTA3/ZjZhYzAzNGFmNjBm/NmZjNTVhNWNmNmFh/Zjc4MmMxZi93d3cu/ZXRzeS5jb20v"
      }
    ]
  },
  {
    "id": "store-example-images-search-3",
    "query": "Cozy winter breakfast table",
    "query_translation_key": "settings.app_store_examples.images.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Get your breakfast room ready for wintertime with these cozy ideas from the walls to the tablescape!",
        "source_page_url": "https://www.frenchcreekfarmhouse.com/2022/01/cozy-winter-breakfast-room.html",
        "image_url": "https://www.frenchcreekfarmhouse.com/wp-content/uploads/2022/01/Cozy-Winter-Breakfast-Room-PIN-683x1024.png",
        "thumbnail_url": "https://imgs.search.brave.com/4XSYg5TWMgn7WigRAAJZ4FiOPiLQATAcnROId_Y6yGI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/ZnJlbmNoY3JlZWtm/YXJtaG91c2UuY29t/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDIy/LzAxL0NvenktV2lu/dGVyLUJyZWFrZmFz/dC1Sb29tLVBJTi02/ODN4MTAyNC5wbmc",
        "source": "frenchcreekfarmhouse.com",
        "favicon_url": "https://imgs.search.brave.com/6qdWBqB1Nt1pMDLK8_V6xaaFIQv-4zMMKf4mLuP_aDU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjdkM2JhYThi/NmE3ZWMwYzBlZDFk/Nzg2MDYxMjI4MGRi/NzM1MTNlY2RlYmM5/MTc1YjYwOGZhZWVl/MGFlZjUzMC93d3cu/ZnJlbmNoY3JlZWtm/YXJtaG91c2UuY29t/Lw"
      },
      {
        "title": "Place setting for a winter dinner party table with a round woven charger plate, white dishes, gold silverware and a sprig of greenery with a pinecone ornament accent",
        "source_page_url": "https://www.midwestlifeandstyle.com/how-to-set-a-table-for-a-cozy-winter-dinner-party/",
        "image_url": "https://www.midwestlifeandstyle.com/wp-content/uploads/2022/12/How-To-Style-A-Cozy-Winter-Tablescape-7-Midwest-Life-and-Style-Blog.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/K6olkp68b_BlKSOFIx2LIopCuxXUW_GvPds-EMvap4c/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/bWlkd2VzdGxpZmVh/bmRzdHlsZS5jb20v/d3AtY29udGVudC91/cGxvYWRzLzIwMjIv/MTIvSG93LVRvLVN0/eWxlLUEtQ296eS1X/aW50ZXItVGFibGVz/Y2FwZS03LU1pZHdl/c3QtTGlmZS1hbmQt/U3R5bGUtQmxvZy5q/cGc",
        "source": "midwestlifeandstyle.com",
        "favicon_url": "https://imgs.search.brave.com/vttf6_uuyTzQhzCxUxINn0iTAVIF73AaK_kLfIgcFsE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMjgzZGU1ZWE5/M2FmZjcyMmMzNGJm/YjE5Yjg2ODYzOWQ5/Zjc3MGRhNjkxNjI1/MDM4OTA4YzRlNTky/OGMzZTViOC93d3cu/bWlkd2VzdGxpZmVh/bmRzdHlsZS5jb20v"
      },
      {
        "title": "6 cozy winter dinner table and centerpiece ideas",
        "source_page_url": "https://stacyling.com/6-cozy-winter-dining-table-and-centerpiece-ideas/",
        "image_url": "https://stacyling.com/wp-content/uploads/2022/01/cozy-winter-dinner-table.jpeg",
        "thumbnail_url": "https://imgs.search.brave.com/3NLVDm9I845373Meba2ycnJv06UGEB9SppBqMJDlVuI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9zdGFj/eWxpbmcuY29tL3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDIyLzAx/L2Nvenktd2ludGVy/LWRpbm5lci10YWJs/ZS5qcGVn",
        "source": "stacyling.com",
        "favicon_url": "https://imgs.search.brave.com/w9I754cEzRVO-ZLZb_XTKXHHhp9oNypVLmFUDF4lxY0/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjRmNGU5NTky/YjI4MjMxNjY1ZGY3/NDQ1ZWZkODcxZWE0/MjViMThkYjIxZWM4/MDkxNjJiZDBkNzhj/ZjU1N2E3NC9zdGFj/eWxpbmcuY29tLw"
      },
      {
        "title": "Several vintage brass candlesticks lined up on pine table with greenery, pinecones, and vintage blue tea and toast plates in winter dining room ideas with ski lodge style.",
        "source_page_url": "https://www.dabblinganddecorating.com/cozy-winter-dining-room-with-ski-lodge-decor-get-the-look/",
        "image_url": "https://www.dabblinganddecorating.com/wp-content/uploads/2024/12/Simple-Winter-Table-Decorations-Cozy-Dining-Ideas2.jpeg",
        "thumbnail_url": "https://imgs.search.brave.com/iOmeibKZUB5ugxFJ6QKwUhioP7HWyHkTyZYCoKpztHE/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/ZGFiYmxpbmdhbmRk/ZWNvcmF0aW5nLmNv/bS93cC1jb250ZW50/L3VwbG9hZHMvMjAy/NC8xMi9TaW1wbGUt/V2ludGVyLVRhYmxl/LURlY29yYXRpb25z/LUNvenktRGluaW5n/LUlkZWFzMi5qcGVn",
        "source": "dabblinganddecorating.com",
        "favicon_url": "https://imgs.search.brave.com/x8QW4J95SrwtEkfl4QP5aOzdDGUoL4EDI8hxcnVwyms/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNmY3MzQ4NTQz/NTAxMzE3YTM2MDVl/NzA0NWExOTc3OWVk/ZTZhODVmNDg1N2Fj/YzQ3MzIyNjVkYjZl/ZjRkMGFhOS93d3cu/ZGFiYmxpbmdhbmRk/ZWNvcmF0aW5nLmNv/bS8"
      }
    ]
  }
]

export default examples;
