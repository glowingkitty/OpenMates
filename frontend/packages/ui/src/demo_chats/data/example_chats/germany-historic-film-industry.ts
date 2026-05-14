// frontend/packages/ui/src/demo_chats/data/example_chats/germany-historic-film-industry.ts
//
// Example chat: Germany's historic film industry
// Extracted from shared chat 8100d302-1d28-48ce-b25d-544b2da04e28
//
// A real conversation about Berlin, Weimar cinema, Studio Babelsberg,
// German Expressionism, and why Hollywood became dominant after the 1930s.

import type { ExampleChat } from "../../types";

export const germanyHistoricFilmIndustryChat: ExampleChat = {
  chat_id: "example-germany-historic-film-industry",
  slug: "germany-historic-film-industry",
  title: "example_chats.germany_historic_film_industry.title",
  summary: "example_chats.germany_historic_film_industry.summary",
  icon: "film",
  category: "movies_tv",
  keywords: [
    "German cinema history", "Berlin film industry", "Weimar cinema",
    "Studio Babelsberg", "Hollywood on the Spree", "German Expressionism",
    "Metropolis 1927", "The Cabinet of Dr. Caligari", "Nosferatu 1922",
    "UFA film studio", "Fritz Lang", "Marlene Dietrich",
    "silent film history", "film noir origins", "Babelsberg Studio history"
  ],
  follow_up_suggestions: [
    "example_chats.germany_historic_film_industry.follow_up_1",
    "example_chats.germany_historic_film_industry.follow_up_2",
    "example_chats.germany_historic_film_industry.follow_up_3",
    "example_chats.germany_historic_film_industry.follow_up_4",
    "example_chats.germany_historic_film_industry.follow_up_5",
    "example_chats.germany_historic_film_industry.follow_up_6",
  ],
  messages: [
    {
      id: "4b2da04e28-91997e08-e02d-47d3-8ad3-7b7de844a730",
      role: "user",
      content: "example_chats.germany_historic_film_industry.user_message_1",
      created_at: 1778707207,
      category: "movies_tv",
    },
    {
      id: "6d75fb27-9979-4a6a-8ccc-e9108a109aa0",
      role: "assistant",
      content: "example_chats.germany_historic_film_industry.assistant_message_1",
      created_at: 1778707213,
      category: "movies_tv",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "24df6a1e-33fe-487f-b3ca-02bfd06bb56a",
      type: "image_result",
      content: `type: image_result
title: "german expressionism horror movies: Movie still from Nosferatu, dir. by Friedrich Murnau, 1922."
source_page_url: "https://www.dailyartmagazine.com/german-expressionism-horror-movies/"
image_url: "https://www.dailyartmagazine.com/wp-content/uploads/2021/10/Nosferatu-768x474.jpg"
thumbnail_url: "https://imgs.search.brave.com/5iSUd1IbwiTSiZQ6nBfMn3K5y1KuBGkCdJRC3TRNtvQ/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/ZGFpbHlhcnRtYWdh/emluZS5jb20vd3At/Y29udGVudC91cGxv/YWRzLzIwMjEvMTAv/Tm9zZmVyYXR1LTc2/OHg0NzQuanBn"
source: dailyartmagazine.com
favicon_url: "https://imgs.search.brave.com/V3y6yUN0Q8_NFn9wV5afjcACAET_MGRe5vCzZtv5j5E/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMTA0ZDBlY2Ex/MmJlYjQyOGQxNTlh/MDZjNGM2NWYyYjRj/NGRlMWRkNTNiZjkz/MWQ0MWNkOTdjNGIz/MDM2Yzc2MS93d3cu/ZGFpbHlhcnRtYWdh/emluZS5jb20v"
hash: 4986339042e3dda6
embed_ref: dailyartmagazine.com-9Tk
app_id: images
skill_id: search`,
      parent_embed_id: "9c18f45f-b54f-42c5-ba58-32dbc15dc549",
      embed_ids: null,
    },
    {
      embed_id: "9c18f45f-b54f-42c5-ba58-32dbc15dc549",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 24df6a1e-33fe-487f-b3ca-02bfd06bb56a|3d28f6d4-b30f-4c07-9460-0c0f0e771baf|832adbf6-6d1a-433a-8c88-dd8f2a4dfb47|aca59efa-abb8-49b9-838a-06a01db2253a|b1e0f4cd-4695-4175-8cea-2ca9322e19ac|d199e3a1-b959-44c2-b9dc-4997b6fd4793
status: finished
query: German Expressionism film stills Caligari Nosferatu
id: 3
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: [
        "24df6a1e-33fe-487f-b3ca-02bfd06bb56a",
        "3d28f6d4-b30f-4c07-9460-0c0f0e771baf",
        "832adbf6-6d1a-433a-8c88-dd8f2a4dfb47",
        "aca59efa-abb8-49b9-838a-06a01db2253a",
        "b1e0f4cd-4695-4175-8cea-2ca9322e19ac",
        "d199e3a1-b959-44c2-b9dc-4997b6fd4793",
      ],
    },
    {
      embed_id: "d199e3a1-b959-44c2-b9dc-4997b6fd4793",
      type: "image_result",
      content: `type: image_result
title: german expressionism nosferatu max schreck as orlok dying
source_page_url: "https://filmfolly.com/features/everything-there-is-to-know-about-german-expressionist-cinema"
image_url: "https://filmfolly.com/wp-content/uploads/2025/09/Everything-there-is-to-know-about-GERMAN-EXPRESSIONIST-CINEMA-21.jpeg"
thumbnail_url: "https://imgs.search.brave.com/L_FfUYZLWsXIccMDUYSuJncqm8np32uRYVOry1JweJI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9maWxt/Zm9sbHkuY29tL3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDI1LzA5/L0V2ZXJ5dGhpbmct/dGhlcmUtaXMtdG8t/a25vdy1hYm91dC1H/RVJNQU4tRVhQUkVT/U0lPTklTVC1DSU5F/TUEtMjEuanBlZw"
source: filmfolly.com
favicon_url: "https://imgs.search.brave.com/Q931M3QcCDwW6DhF6H1Ij5VJwJdUv5x47RILeKWND5k/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGY1ZDZkNmVh/NzkxY2I2OGM4NTk5/MmM4Mjk3YTBjNTUx/YWZlZDAwOTBhMTMy/OTZkMDMwOTUyNmYz/MzdiZmE3Ny9maWxt/Zm9sbHkuY29tLw"
hash: 28d076dd8a4de2bf
embed_ref: filmfolly.com-HVC
app_id: images
skill_id: search`,
      parent_embed_id: "9c18f45f-b54f-42c5-ba58-32dbc15dc549",
      embed_ids: null,
    },
    {
      embed_id: "b1e0f4cd-4695-4175-8cea-2ca9322e19ac",
      type: "image_result",
      content: `type: image_result
title: german expressionism nosferatu
source_page_url: "https://filmfolly.com/features/everything-there-is-to-know-about-german-expressionist-cinema"
image_url: "https://filmfolly.com/wp-content/uploads/2025/09/Everything-there-is-to-know-about-GERMAN-EXPRESSIONIST-CINEMA-19.jpeg"
thumbnail_url: "https://imgs.search.brave.com/ZqUZi04WURHAvLcMzlbcHx6EgKh34NBnotlGauGY4_Q/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9maWxt/Zm9sbHkuY29tL3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDI1LzA5/L0V2ZXJ5dGhpbmct/dGhlcmUtaXMtdG8t/a25vdy1hYm91dC1H/RVJNQU4tRVhQUkVT/U0lPTklTVC1DSU5F/TUEtMTkuanBlZw"
source: filmfolly.com
favicon_url: "https://imgs.search.brave.com/Q931M3QcCDwW6DhF6H1Ij5VJwJdUv5x47RILeKWND5k/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGY1ZDZkNmVh/NzkxY2I2OGM4NTk5/MmM4Mjk3YTBjNTUx/YWZlZDAwOTBhMTMy/OTZkMDMwOTUyNmYz/MzdiZmE3Ny9maWxt/Zm9sbHkuY29tLw"
hash: 3dd50f78e31a5a06
embed_ref: filmfolly.com-P5u
app_id: images
skill_id: search`,
      parent_embed_id: "9c18f45f-b54f-42c5-ba58-32dbc15dc549",
      embed_ids: null,
    },
    {
      embed_id: "aca59efa-abb8-49b9-838a-06a01db2253a",
      type: "image_result",
      content: `type: image_result
title: The Student of Prague (1913) German Expressionism in Film
source_page_url: "https://www.classicmoviehub.com/blog/silents-are-golden-just-what-the-heck-was-german-expressionism/"
image_url: "https://i1.wp.com/www.classicmoviehub.com/blog/wp-content/uploads/2018/10/The_Student_of_Prague_1913_German_Expressionism_Film.jpg?resize=600,512"
thumbnail_url: "https://imgs.search.brave.com/JDtIeVXpsiCU0KcUTX6vPITLVbxcTB__aaitlRcLZ0E/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pMS53/cC5jb20vd3d3LmNs/YXNzaWNtb3ZpZWh1/Yi5jb20vYmxvZy93/cC1jb250ZW50L3Vw/bG9hZHMvMjAxOC8x/MC9UaGVfU3R1ZGVu/dF9vZl9QcmFndWVf/MTkxM19HZXJtYW5f/RXhwcmVzc2lvbmlz/bV9GaWxtLmpwZz9y/ZXNpemU9NjAwLDUx/Mg"
source: classicmoviehub.com
favicon_url: "https://imgs.search.brave.com/vbLP-tppOxF_fij6LdakJEOPHbEABH1ZYLlKEXNjrl4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGMzNTE5OTMx/N2I0NmUxMWZhYjM5/ZDc1ODBhZDUwZmI0/NmJmYmU3ZjIyZGIw/MDE1NDBkNTEwMmJl/ZjEyMmVjMi93d3cu/Y2xhc3NpY21vdmll/aHViLmNvbS8"
hash: 192367d50e658bd7
embed_ref: classicmoviehub.com-4M7
app_id: images
skill_id: search`,
      parent_embed_id: "9c18f45f-b54f-42c5-ba58-32dbc15dc549",
      embed_ids: null,
    },
    {
      embed_id: "832adbf6-6d1a-433a-8c88-dd8f2a4dfb47",
      type: "image_result",
      content: `type: image_result
title: Nosferatu (1922) Still German Expressionism
source_page_url: "https://www.classicmoviehub.com/blog/silents-are-golden-just-what-the-heck-was-german-expressionism/"
image_url: "https://i2.wp.com/www.classicmoviehub.com/blog/wp-content/uploads/2018/10/Nosferatu_1922_Still_German_Expressionism.png?resize=600,407"
thumbnail_url: "https://imgs.search.brave.com/qIuNlUztQew4U-eDAnumO5nkprfKS9tDs0wjh9yrrjM/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pMi53/cC5jb20vd3d3LmNs/YXNzaWNtb3ZpZWh1/Yi5jb20vYmxvZy93/cC1jb250ZW50L3Vw/bG9hZHMvMjAxOC8x/MC9Ob3NmZXJhdHVf/MTkyMl9TdGlsbF9H/ZXJtYW5fRXhwcmVz/c2lvbmlzbS5wbmc_/cmVzaXplPTYwMCw0/MDc"
source: classicmoviehub.com
favicon_url: "https://imgs.search.brave.com/vbLP-tppOxF_fij6LdakJEOPHbEABH1ZYLlKEXNjrl4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGMzNTE5OTMx/N2I0NmUxMWZhYjM5/ZDc1ODBhZDUwZmI0/NmJmYmU3ZjIyZGIw/MDE1NDBkNTEwMmJl/ZjEyMmVjMi93d3cu/Y2xhc3NpY21vdmll/aHViLmNvbS8"
hash: e0e2f4084d817a72
embed_ref: classicmoviehub.com-hxk
app_id: images
skill_id: search`,
      parent_embed_id: "9c18f45f-b54f-42c5-ba58-32dbc15dc549",
      embed_ids: null,
    },
    {
      embed_id: "3d28f6d4-b30f-4c07-9460-0c0f0e771baf",
      type: "image_result",
      content: `type: image_result
title: german expressionism nosferatu fw murnau movie still
source_page_url: "https://www.thecollector.com/german-expressionism-film-noir/"
image_url: "https://cdn.thecollector.com/wp-content/uploads/2023/11/german-expressionism-nosferatu-fw-murnau-movie-still.jpg?width=1200&quality=100&dpr=2"
thumbnail_url: "https://imgs.search.brave.com/bE0fJcCFVRGkNaWPX4PnYv1r7mh6cz6g6EGdUnR6hRs/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/dGhlY29sbGVjdG9y/LmNvbS93cC1jb250/ZW50L3VwbG9hZHMv/MjAyMy8xMS9nZXJt/YW4tZXhwcmVzc2lv/bmlzbS1ub3NmZXJh/dHUtZnctbXVybmF1/LW1vdmllLXN0aWxs/LmpwZz93aWR0aD0x/MjAwJnF1YWxpdHk9/MTAwJmRwcj0y"
source: thecollector.com
favicon_url: "https://imgs.search.brave.com/rn9MdwfLDT4XbKeI4o-9kxVSK9Ah8YH3UkvECdeyMcc/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZWM4YWZlYzBh/ZjFiOWMyZjc2MWUz/OGUyYTU5MGNhYTI0/MjY5YTRjZDQ4OTRm/OTIwOWYyMTZlM2E5/MTI3MWM5ZS93d3cu/dGhlY29sbGVjdG9y/LmNvbS8"
hash: b28bf3b9acfb176c
embed_ref: thecollector.com-FmU
app_id: images
skill_id: search`,
      parent_embed_id: "9c18f45f-b54f-42c5-ba58-32dbc15dc549",
      embed_ids: null,
    },
    {
      embed_id: "ba5d9c71-51f3-4282-9f1c-2afc141a37d0",
      type: "image_result",
      content: `type: image_result
title: ""
source_page_url: "https://www.studiobabelsberg.com/about-us/commitment-and-history/"
image_url: "https://www.studiobabelsberg.com/content/uploads/2025/01/glashaus-glass-house-studio-stage-babelsberg-aspect-ratio-1760-1004.jpg?x13912"
thumbnail_url: "https://imgs.search.brave.com/wgvO1yJAl5FHrhy7T68ia5ba-DVkYpMEZ3v3R73t8jo/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20vY29u/dGVudC91cGxvYWRz/LzIwMjUvMDEvZ2xh/c2hhdXMtZ2xhc3Mt/aG91c2Utc3R1ZGlv/LXN0YWdlLWJhYmVs/c2JlcmctYXNwZWN0/LXJhdGlvLTE3NjAt/MTAwNC5qcGc_eDEz/OTEy"
source: studiobabelsberg.com
favicon_url: "https://imgs.search.brave.com/xipgJiq_LyDSMnMP0knOA4goaY6gwrhGUrGeld3YlY8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTlhNGQ4NGE2/MDVjOGE4NjEwMjk3/ZjNmNmZiMjg5MzJm/OTY5NzJjNGM3NGMz/Y2NjNWRhNWUwOTMy/YTI3YjliNS93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20v"
hash: 34501cca0105f5f3
embed_ref: studiobabelsberg.com-PK8
app_id: images
skill_id: search`,
      parent_embed_id: "012d5852-9cb8-4e79-a145-75bfba159a17",
      embed_ids: null,
    },
    {
      embed_id: "0cf571c1-7d8c-4502-96ac-2a5ed7a51429",
      type: "image_result",
      content: `type: image_result
title: STUDIO BABELSBERG – THE OLDEST FILM STUDIO IN THE WORLD
source_page_url: "https://portlandgermanfilmfestival.com/studio-babelsberg-the-oldest-film-studio-in-the-world/"
image_url: "https://portlandgermanfilmfestival.com/wp17/wp-content/uploads/2019/09/studio-babelsberg-entrance-770x434.jpg"
thumbnail_url: "https://imgs.search.brave.com/EQSQ9TdUtlT6XN8YKrsOAl1bw1tOrGnoh_An1ugzSkE/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9wb3J0/bGFuZGdlcm1hbmZp/bG1mZXN0aXZhbC5j/b20vd3AxNy93cC1j/b250ZW50L3VwbG9h/ZHMvMjAxOS8wOS9z/dHVkaW8tYmFiZWxz/YmVyZy1lbnRyYW5j/ZS03NzB4NDM0Lmpw/Zw"
source: portlandgermanfilmfestival.com
favicon_url: "https://imgs.search.brave.com/FHqXaNDpskKKJzBVkBH7RgF7kYkNH57EEt1_pz-RnPE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZGQ1NWVjYTY1/ZjYyYWI0OGVmZjdh/N2M3MjZhZDBjZTRj/OWJjMWFkNzNlYWUx/MGU4ZjdmMjRlM2Fj/YTA1NzYyOS9wb3J0/bGFuZGdlcm1hbmZp/bG1mZXN0aXZhbC5j/b20v"
hash: 5a8f20de3f641cf0
embed_ref: portlandgermanfilmfestival.com-7p8
app_id: images
skill_id: search`,
      parent_embed_id: "012d5852-9cb8-4e79-a145-75bfba159a17",
      embed_ids: null,
    },
    {
      embed_id: "366f07b5-f7c3-47df-8f9b-8ac4d1c3076a",
      type: "image_result",
      content: `type: image_result
title: ""
source_page_url: "https://www.studiobabelsberg.com/en/sound-stages/stages-4-7/"
image_url: "https://www.studiobabelsberg.com/content/uploads/2025/01/csm_studio-4-7-stage-filmkulisse-film-set-studio-babelsberg_fded57274a-aspect-ratio-2000-873.jpg?x97219"
thumbnail_url: "https://imgs.search.brave.com/L0-i9Ptdbp78nKWzoeo-ziEARIllkRvFCVMVdhPZX4I/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20vY29u/dGVudC91cGxvYWRz/LzIwMjUvMDEvY3Nt/X3N0dWRpby00LTct/c3RhZ2UtZmlsbWt1/bGlzc2UtZmlsbS1z/ZXQtc3R1ZGlvLWJh/YmVsc2JlcmdfZmRl/ZDU3Mjc0YS1hc3Bl/Y3QtcmF0aW8tMjAw/MC04NzMuanBnP3g5/NzIxOQ"
source: studiobabelsberg.com
favicon_url: "https://imgs.search.brave.com/xipgJiq_LyDSMnMP0knOA4goaY6gwrhGUrGeld3YlY8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTlhNGQ4NGE2/MDVjOGE4NjEwMjk3/ZjNmNmZiMjg5MzJm/OTY5NzJjNGM3NGMz/Y2NjNWRhNWUwOTMy/YTI3YjliNS93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20v"
hash: 06f23a5457b98f12
embed_ref: studiobabelsberg.com-Ov3
app_id: images
skill_id: search`,
      parent_embed_id: "012d5852-9cb8-4e79-a145-75bfba159a17",
      embed_ids: null,
    },
    {
      embed_id: "78433499-2c99-4042-a65a-b939296440d1",
      type: "image_result",
      content: `type: image_result
title: ""
source_page_url: "https://www.studiobabelsberg.com/services/prop-department/"
image_url: "https://www.studiobabelsberg.com/content/uploads/2025/01/csm_filmstandort-deutschland-filming-in-germany-studio-babelsberg-b_2ea2cc47c8-aspect-ratio-980-456-1.jpg?x69680"
thumbnail_url: "https://imgs.search.brave.com/EQH9f_PuLAvfBLF3ib0MRltDEZkmKPVUJyfLsrfyVkc/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20vY29u/dGVudC91cGxvYWRz/LzIwMjUvMDEvY3Nt/X2ZpbG1zdGFuZG9y/dC1kZXV0c2NobGFu/ZC1maWxtaW5nLWlu/LWdlcm1hbnktc3R1/ZGlvLWJhYmVsc2Jl/cmctYl8yZWEyY2M0/N2M4LWFzcGVjdC1y/YXRpby05ODAtNDU2/LTEuanBnP3g2OTY4/MA"
source: studiobabelsberg.com
favicon_url: "https://imgs.search.brave.com/xipgJiq_LyDSMnMP0knOA4goaY6gwrhGUrGeld3YlY8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTlhNGQ4NGE2/MDVjOGE4NjEwMjk3/ZjNmNmZiMjg5MzJm/OTY5NzJjNGM3NGMz/Y2NjNWRhNWUwOTMy/YTI3YjliNS93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20v"
hash: 4b20f67213b41be8
embed_ref: studiobabelsberg.com-4Yi
app_id: images
skill_id: search`,
      parent_embed_id: "012d5852-9cb8-4e79-a145-75bfba159a17",
      embed_ids: null,
    },
    {
      embed_id: "6716cff7-3fcc-44ae-89f9-b9f6af47742b",
      type: "image_result",
      content: `type: image_result
title: ""
source_page_url: "https://www.studiobabelsberg.com/en/sound-stages/stages-4-7/"
image_url: "https://www.studiobabelsberg.com/content/uploads/2025/02/studio-babelsberg-stage-studio-6-b-1-aspect-ratio-1500-800.jpg?x97219"
thumbnail_url: "https://imgs.search.brave.com/-6dCFDNtqxmDDF_Uj5IJ2UB1_QvDvCiy00LcC-ztdZQ/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20vY29u/dGVudC91cGxvYWRz/LzIwMjUvMDIvc3R1/ZGlvLWJhYmVsc2Jl/cmctc3RhZ2Utc3R1/ZGlvLTYtYi0xLWFz/cGVjdC1yYXRpby0x/NTAwLTgwMC5qcGc_/eDk3MjE5"
source: studiobabelsberg.com
favicon_url: "https://imgs.search.brave.com/xipgJiq_LyDSMnMP0knOA4goaY6gwrhGUrGeld3YlY8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTlhNGQ4NGE2/MDVjOGE4NjEwMjk3/ZjNmNmZiMjg5MzJm/OTY5NzJjNGM3NGMz/Y2NjNWRhNWUwOTMy/YTI3YjliNS93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20v"
hash: 809f671737469a15
embed_ref: studiobabelsberg.com-Vej
app_id: images
skill_id: search`,
      parent_embed_id: "012d5852-9cb8-4e79-a145-75bfba159a17",
      embed_ids: null,
    },
    {
      embed_id: "cffce813-96ac-411e-8005-2b545ab241ab",
      type: "image_result",
      content: `type: image_result
title: "Two photos; one present-day of Oskar Jakob, a man in his 90s, and the other circa-1920s of Robert Lusser, a man in his 30s."
source_page_url: "https://www.latimes.com/archives/la-xpm-1996-09-22-ca-46386-story.html"
image_url: "https://ca-times.brightspotcdn.com/dims4/default/78b1664/2147483647/strip/true/crop/2991x2000+5+0/resize/320x214!/quality/75/?url=https://california-times-brightspot.s3.amazonaws.com/a5/21/d52f7bcb4bcaa31fe56263145ee4/oe-rico-my-nazi-grandfather.jpg"
thumbnail_url: "https://imgs.search.brave.com/BEuSgvMc6Y8XrWpdskyYWJZ0bdRnMuFch9uFcAFwRw8/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jYS10/aW1lcy5icmlnaHRz/cG90Y2RuLmNvbS9k/aW1zNC9kZWZhdWx0/Lzc4YjE2NjQvMjE0/NzQ4MzY0Ny9zdHJp/cC90cnVlL2Nyb3Av/Mjk5MXgyMDAwKzUr/MC9yZXNpemUvMzIw/eDIxNCEvcXVhbGl0/eS83NS8_dXJsPWh0/dHBzOi8vY2FsaWZv/cm5pYS10aW1lcy1i/cmlnaHRzcG90LnMz/LmFtYXpvbmF3cy5j/b20vYTUvMjEvZDUy/ZjdiY2I0YmNhYTMx/ZmU1NjI2MzE0NWVl/NC9vZS1yaWNvLW15/LW5hemktZ3JhbmRm/YXRoZXIuanBn"
source: latimes.com
favicon_url: "https://imgs.search.brave.com/EIRey0HaEsL1IV9fnxScQLjHB6lv2fJwFlos_6z5T74/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDFlNWJiNjNk/ZGIzOWIzYTU2ODgz/MDYxMDMxNTY1ZjU1/NTdmNzEzMmQwMDRk/NDZmYTc3Mzg2NTA4/ZjdjOWVlMi93d3cu/bGF0aW1lcy5jb20v"
hash: b37c657faffeed85
embed_ref: latimes.com-v4n
app_id: images
skill_id: search`,
      parent_embed_id: "012d5852-9cb8-4e79-a145-75bfba159a17",
      embed_ids: null,
    },
    {
      embed_id: "012d5852-9cb8-4e79-a145-75bfba159a17",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 0cf571c1-7d8c-4502-96ac-2a5ed7a51429|366f07b5-f7c3-47df-8f9b-8ac4d1c3076a|78433499-2c99-4042-a65a-b939296440d1|ba5d9c71-51f3-4282-9f1c-2afc141a37d0|6716cff7-3fcc-44ae-89f9-b9f6af47742b|cffce813-96ac-411e-8005-2b545ab241ab
status: finished
query: Babelsberg Studio 1920s historical photo
id: 1
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: [
        "0cf571c1-7d8c-4502-96ac-2a5ed7a51429",
        "366f07b5-f7c3-47df-8f9b-8ac4d1c3076a",
        "78433499-2c99-4042-a65a-b939296440d1",
        "ba5d9c71-51f3-4282-9f1c-2afc141a37d0",
        "6716cff7-3fcc-44ae-89f9-b9f6af47742b",
        "cffce813-96ac-411e-8005-2b545ab241ab",
      ],
    },
    {
      embed_id: "94788153-5b5a-4db8-8f56-71e34a1ada19",
      type: "image_result",
      content: `type: image_result
title: Metropolis 1927 Movie Poster re-release 1986 poster design Floating Black
source_page_url: "https://www.etsy.com/listing/656619267/metropolis-1927-movie-poster-re-release"
image_url: "https://i.etsystatic.com/12529226/r/il/a73263/1675049690/il_794xN.1675049690_lzsx.jpg"
thumbnail_url: "https://imgs.search.brave.com/IPflWhyAez1DVXnbGEmaVm2oCHmGXKNxbVkJC3laR6g/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pLmV0/c3lzdGF0aWMuY29t/LzEyNTI5MjI2L3Iv/aWwvYTczMjYzLzE2/NzUwNDk2OTAvaWxf/Nzk0eE4uMTY3NTA0/OTY5MF9senN4Lmpw/Zw"
source: etsy.com
favicon_url: "https://imgs.search.brave.com/VV6KUN1qWhB24EKDo1dIESK_1GyC0VpfAFwGmI97i6w/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjcwZDg1MmI2/YTMzN2YwMThkMzVj/YmIwZmU4YTcwMTA3/ZjZhYzAzNGFmNjBm/NmZjNTVhNWNmNmFh/Zjc4MmMxZi93d3cu/ZXRzeS5jb20v"
hash: 42135e64762fc828
embed_ref: etsy.com-Uab
app_id: images
skill_id: search`,
      parent_embed_id: "6b9178c9-9e57-4d13-8cb8-b89ed5888927",
      embed_ids: null,
    },
    {
      embed_id: "37b60207-025d-4a10-a5c0-37dcd15ef649",
      type: "image_result",
      content: `type: image_result
title: "Item preview, Movie Poster for 1927 Metropolis (German ver B) designed and sold by ArchimedesPrime."
source_page_url: "https://www.redbubble.com/shop/metropolis+posters"
image_url: "https://ih1.redbubble.net/image.4823227813.5472/fposter,small,wall_texture,square_product,600x600.jpg"
thumbnail_url: "https://imgs.search.brave.com/tEoHQ7bb4phnOxIArfC1Kr6W0Wd34rKODYhcxbefNv8/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9paDEu/cmVkYnViYmxlLm5l/dC9pbWFnZS40ODIz/MjI3ODEzLjU0NzIv/ZnBvc3RlcixzbWFs/bCx3YWxsX3RleHR1/cmUsc3F1YXJlX3By/b2R1Y3QsNjAweDYw/MC5qcGc"
source: redbubble.com
favicon_url: "https://imgs.search.brave.com/4WmgjfI8kWSQZ5Hl6_EB-RT1yKWkvtk8JRANzdMBlos/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODMxOGUxMTJh/NTA3YWNiNjc0ZWRj/Nzg4OTQ3M2UzYzI5/NGU1OTljMzhkNGY0/MzkwYzU2YmMxZWY0/ZmI4MWYyNi93d3cu/cmVkYnViYmxlLmNv/bS8"
hash: d4312b9869cd4d52
embed_ref: redbubble.com-Vjc
app_id: images
skill_id: search`,
      parent_embed_id: "6b9178c9-9e57-4d13-8cb8-b89ed5888927",
      embed_ids: null,
    },
    {
      embed_id: "d3dab440-d8c3-471d-92f0-79ef299932f2",
      type: "image_result",
      content: `type: image_result
title: "Item preview, Fritz Lang METROPOLIS 1927 Science Fiction Film Vintage Movie designed and sold by retroposters."
source_page_url: "https://www.redbubble.com/shop/metropolis+posters"
image_url: "https://ih1.redbubble.net/image.883113843.3856/fposter,small,wall_texture,square_product,600x600.jpg"
thumbnail_url: "https://imgs.search.brave.com/4Ppj5cCgyJE8M1Wr_ZCtZvQVfwMnql2J4gjdWsUM344/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9paDEu/cmVkYnViYmxlLm5l/dC9pbWFnZS44ODMx/MTM4NDMuMzg1Ni9m/cG9zdGVyLHNtYWxs/LHdhbGxfdGV4dHVy/ZSxzcXVhcmVfcHJv/ZHVjdCw2MDB4NjAw/LmpwZw"
source: redbubble.com
favicon_url: "https://imgs.search.brave.com/4WmgjfI8kWSQZ5Hl6_EB-RT1yKWkvtk8JRANzdMBlos/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODMxOGUxMTJh/NTA3YWNiNjc0ZWRj/Nzg4OTQ3M2UzYzI5/NGU1OTljMzhkNGY0/MzkwYzU2YmMxZWY0/ZmI4MWYyNi93d3cu/cmVkYnViYmxlLmNv/bS8"
hash: eb4de3bd933610b2
embed_ref: redbubble.com-ogN
app_id: images
skill_id: search`,
      parent_embed_id: "6b9178c9-9e57-4d13-8cb8-b89ed5888927",
      embed_ids: null,
    },
    {
      embed_id: "c40d623f-a8fc-4481-b294-6ec21a22d45c",
      type: "image_result",
      content: `type: image_result
title: "Item preview, Fritz Lang's Metropolis Movie Poster 1927 designed and sold by ArchimedesPrime."
source_page_url: "https://www.redbubble.com/shop/metropolis+posters"
image_url: "https://ih1.redbubble.net/image.5562255179.8916/fposter,small,wall_texture,square_product,600x600.jpg"
thumbnail_url: "https://imgs.search.brave.com/Qhpv7Jkx3v6F6BkkAhhO2y0HoF5C0Dx_cuTUfA_nJ6E/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9paDEu/cmVkYnViYmxlLm5l/dC9pbWFnZS41NTYy/MjU1MTc5Ljg5MTYv/ZnBvc3RlcixzbWFs/bCx3YWxsX3RleHR1/cmUsc3F1YXJlX3By/b2R1Y3QsNjAweDYw/MC5qcGc"
source: redbubble.com
favicon_url: "https://imgs.search.brave.com/4WmgjfI8kWSQZ5Hl6_EB-RT1yKWkvtk8JRANzdMBlos/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODMxOGUxMTJh/NTA3YWNiNjc0ZWRj/Nzg4OTQ3M2UzYzI5/NGU1OTljMzhkNGY0/MzkwYzU2YmMxZWY0/ZmI4MWYyNi93d3cu/cmVkYnViYmxlLmNv/bS8"
hash: e91fa7a491139462
embed_ref: redbubble.com-JYc
app_id: images
skill_id: search`,
      parent_embed_id: "6b9178c9-9e57-4d13-8cb8-b89ed5888927",
      embed_ids: null,
    },
    {
      embed_id: "e8753394-3503-4bda-800c-a940ff7a5452",
      type: "image_result",
      content: `type: image_result
title: Metropolis Sci-Fi Movie Poster Jigsaw Puzzle
source_page_url: "https://gcfphotography.com/featured/metropolis-1927-nomad-art-and-design.html?product=poster"
image_url: "https://render.fineartamerica.com/images/rendered/small/flat/puzzle/images-medium-5/metropolis-1927-nomad-art-and-design.jpg?&targetx=-13&targety=0&imagewidth=776&imageheight=1000&modelwidth=750&modelheight=1000&backgroundcolor=262728&orientation=1&producttype=puzzle-18-24&brightness=117&v=6"
thumbnail_url: "https://imgs.search.brave.com/-V-nb2TEz6B8AEcS5XMrdKUSLSm-6KJkg2ny1KZSFEI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9yZW5k/ZXIuZmluZWFydGFt/ZXJpY2EuY29tL2lt/YWdlcy9yZW5kZXJl/ZC9zbWFsbC9mbGF0/L3B1enpsZS9pbWFn/ZXMtbWVkaXVtLTUv/bWV0cm9wb2xpcy0x/OTI3LW5vbWFkLWFy/dC1hbmQtZGVzaWdu/LmpwZz8mdGFyZ2V0/eD0tMTMmdGFyZ2V0/eT0wJmltYWdld2lk/dGg9Nzc2JmltYWdl/aGVpZ2h0PTEwMDAm/bW9kZWx3aWR0aD03/NTAmbW9kZWxoZWln/aHQ9MTAwMCZiYWNr/Z3JvdW5kY29sb3I9/MjYyNzI4Jm9yaWVu/dGF0aW9uPTEmcHJv/ZHVjdHR5cGU9cHV6/emxlLTE4LTI0JmJy/aWdodG5lc3M9MTE3/JnY9Ng"
source: gcfphotography.com
favicon_url: "https://imgs.search.brave.com/JGizfZrc3BGLs_G9Mvj9jLRiumHPQvABdHNjTNIr8p0/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGY5MDQ3MzFk/MzhiMzYyZDE1MWI3/NDBlYTMxOGU4ODQy/MGQ5NTAxNjdhMWVk/YTQxNWY0M2RkMmI4/ZTI5MWVlYS9nY2Zw/aG90b2dyYXBoeS5j/b20v"
hash: 7751938f786b5540
embed_ref: gcfphotography.com-X8u
app_id: images
skill_id: search`,
      parent_embed_id: "6b9178c9-9e57-4d13-8cb8-b89ed5888927",
      embed_ids: null,
    },
    {
      embed_id: "6b9178c9-9e57-4d13-8cb8-b89ed5888927",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 5
embed_ids: 94788153-5b5a-4db8-8f56-71e34a1ada19|37b60207-025d-4a10-a5c0-37dcd15ef649|d3dab440-d8c3-471d-92f0-79ef299932f2|c40d623f-a8fc-4481-b294-6ec21a22d45c|e8753394-3503-4bda-800c-a940ff7a5452
status: finished
query: Metropolis 1927 movie poster or set design
id: 2
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: [
        "94788153-5b5a-4db8-8f56-71e34a1ada19",
        "37b60207-025d-4a10-a5c0-37dcd15ef649",
        "d3dab440-d8c3-471d-92f0-79ef299932f2",
        "c40d623f-a8fc-4481-b294-6ec21a22d45c",
        "e8753394-3503-4bda-800c-a940ff7a5452",
      ],
    },
    {
      embed_id: "a207c870-ea93-424d-b702-3b9b4c9ba04c",
      type: "website",
      content: `type: search_result
title: Babelsberg Studio - Wikipedia
url: "https://en.wikipedia.org/wiki/Babelsberg_Studio"
description: "In 1911, the film production company Deutsche Bioscope bought the current site in Babelsberg and built its first glasshouse film studio (early studios designed to take advantage of natural light) in Neubabelsberg. The company had been originally formed by Jules Greenbaum in 1899 and incorporated in 1902..."
page_age: "September 29, 2025"
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/jYnjvcGIfi6Cs2QGaZAlow3XGfEMtH2o6Ol6BpDZA8c/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy8y/LzI5L0ZpbG1zdHVk/aW9fQmFiZWxzYmVy/Z19FaW5nYW5nLmpw/Zw"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/2/29/Filmstudio_Babelsberg_Eingang.jpg"
extra_snippets: "Babelsberg Film Studio (German: Filmstudio Babelsberg) (also known as Studio Babelsberg), located in Potsdam-Babelsberg outside Berlin, Germany, is the oldest large-scale film studio in the world, producing films since 1912. With a total area of about 460,000 square metres (5,000,000 sq ft) ...|In 1911, the film production company Deutsche Bioscope bought the current site in Babelsberg and built its first glasshouse film studio (early studios designed to take advantage of natural light) in Neubabelsberg. The company had been originally formed by Jules Greenbaum in 1899 and incorporated in 1902.|The first filming in Babelsberg began as early as February 1912 for The Dance of Death by Danish director Urban Gad. In 1920 the Deutsche Bioscop Gesellschaft merged with Erich Pommer's Decla-Film GmbH to form \\"Decla-Bioscop\\". In 1928, Decla-Bioscop merged with Universum Film AG (Ufa) which had been founded in 1917.|Spaceflight owes director Fritz Lang and the film team of the science fiction silent film Woman in the Moon (1929), completely made in the Babelsberg studios, a famous achievement: the countdown was born in Babelsberg."
hash: cdb4e557c45d25e5
embed_ref: en.wikipedia.org-RRE
app_id: web
skill_id: search`,
      parent_embed_id: "4dc639be-e6f2-40a8-99f5-f0dc0884cb4c",
      embed_ids: null,
    },
    {
      embed_id: "0a9700c6-4842-4daf-bdca-bb961a33aee6",
      type: "website",
      content: `type: search_result
title: Cinema of Germany - Wikipedia
url: "https://en.wikipedia.org/wiki/Cinema_of_Germany"
description: "Babelsberg remained the centre of German filmmaking for many years, became the largest film studio in Europe and produced most of the films in this \\"golden era\\" of German cinema. In essence it was \\"the German equivalent to Hollywood\\"."
page_age: 3 weeks ago
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/2bxv63p9XD1LlDj_j53N29drxKNwSHB8TimiGIobP28/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvZW4vMC8wOC9T/Y2hyZWNrLmpwZw"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/en/0/08/Schreck.jpg"
extra_snippets: "Babelsberg Studio, which was incorporated into UFA, expanded massively and gave the German film industry a highly developed infrastructure. Babelsberg remained the centre of German filmmaking for many years, became the largest film studio in Europe and produced most of the films in this \\"golden era\\" of German cinema. In essence it was \\"the German equivalent to Hollywood\\".|The Expressionist movement began to wane during the mid-1920s, but perhaps the fact that its main creators moved to Hollywood, California, allowed this style to remain influential in world cinema for years to come, particularly in American horror films and film noir and in the works of European directors such as Jean Cocteau and Ingmar Bergman.|The cinema of Germany can be traced back to the late 19th century. The film industry in Germany made major technical and artistic contributions to early film, broadcasting and television technology. Babelsberg became a household synonym for the early 20th century film industry in Europe, similar to Hollywood later.|The polarised politics of the Weimar period were also reflected in some of its films. A series of patriotic films about Prussian history, starring Otto Gebühr as Frederick the Great were produced throughout the 1920s and were popular with the nationalist right-wing, who strongly criticised the \\"asphalt\\" films' decadence.|The legacy of Weimar era filmmaking spreads into later movements as well such as noir lighting. it just shows how the stylistic techniques in 1920s German cinema especially the use of shadows, urban alienation, and how expressionism resurfaced in American noir of the 1940s and beyond. Despite the things caused by the Nazi period, The Weimar Republic remains one of the most influential points in film history."
hash: 0e69017a321f054d
embed_ref: en.wikipedia.org-Vho
app_id: web
skill_id: search`,
      parent_embed_id: "4dc639be-e6f2-40a8-99f5-f0dc0884cb4c",
      embed_ids: null,
    },
    {
      embed_id: "c8aa3905-8f5b-4b87-8847-e5c9787284ae",
      type: "website",
      content: `type: search_result
title: Commitment and History / Studio Babelsberg
url: "https://www.studiobabelsberg.com/about-us/commitment-and-history/"
description: "The late 1920s recession nearly bankrupts Ufa. After the Nazis seize power in 1933, the Propaganda Ministry commissions Nazi films, prompting filmmakers like Josef von Sternberg, Fritz Lang, Ernst Lubitsch and Billy Wilder, as well as Marlene ..."
page_age: "January 7, 2026"
profile_name: Studio Babelsberg
meta_url_favicon: "https://imgs.search.brave.com/xipgJiq_LyDSMnMP0knOA4goaY6gwrhGUrGeld3YlY8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTlhNGQ4NGE2/MDVjOGE4NjEwMjk3/ZjNmNmZiMjg5MzJm/OTY5NzJjNGM3NGMz/Y2NjNWRhNWUwOTMy/YTI3YjliNS93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20v"
thumbnail_src: "https://imgs.search.brave.com/7cxRLF86l1eAfljBHlKQ5lFOGvai5Is2AUiDI2OUsR8/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/c3R1ZGlvYmFiZWxz/YmVyZy5jb20vY29u/dGVudC91cGxvYWRz/LzIwMjUvMDEvb2cu/anBn"
thumbnail_original: "https://www.studiobabelsberg.com/content/uploads/2025/01/og.jpg"
extra_snippets: "The late 1920s recession nearly bankrupts Ufa. After the Nazis seize power in 1933, the Propaganda Ministry commissions Nazi films, prompting filmmakers like Josef von Sternberg, Fritz Lang, Ernst Lubitsch and Billy Wilder, as well as Marlene Dietrich, to leave for Hollywood. To distract the German audience from the war, the studio focuses on entertainment, producing MÜNCHHAUSEN and FEUERZANGENBOWLE, starring Zarah Leander, Heinz Rühmann, and Hans Albers.|A jury composed of CUPRA Chief Brand Officer Ignacio Prieto, CUPRA ambassadors J.A. Bayona and Daniel Brühl, Berlinale Festival Director Tricia Tuttle, and producer Marcus Loges from Studio Babelsberg will select finalists who will receive mentoring and production support from Studio Babelsberg to bring their visions to life.|In 2004, Vivendi sells Studio Babelsberg to FBB – Filmbetriebe Berlin Brandenburg GmbH. In 2005, Studio Babelsberg becomes a stock corporation. 2007 is one of its most successful years, producing 12 films, including THE READER and THE BOURNE ULTIMATUM.|In 2012, Studio Babelsberg celebrates its 100th anniversary. The following years the studio thrives with productions like THE HUNGER GAMES: MOCKINJAY, BRIDGE OF SPIES, THE GRAND BUDAPEST HOTEL and CAPTAIN AMERICA: CIVIL WAR, earning global acclaim."
hash: c86deb67443b7cb3
embed_ref: studiobabelsberg.com-p88
app_id: web
skill_id: search`,
      parent_embed_id: "4dc639be-e6f2-40a8-99f5-f0dc0884cb4c",
      embed_ids: null,
    },
    {
      embed_id: "4ac7cb99-9b6b-4675-8c61-412c7035414b",
      type: "website",
      content: `type: search_result
title: STUDIO BABELSBERG – THE OLDEST FILM STUDIO IN THE WORLD | Portland German Film Festival
url: "https://portlandgermanfilmfestival.com/studio-babelsberg-the-oldest-film-studio-in-the-world/"
description: "After the Nazis’ accession to ... try their luck in Hollywood. During this era, the main task of Babelsberg Studios was the production of entertainment films designed to distract German audiences from war-related difficulties...."
page_age: ""
profile_name: Portlandgermanfilmfestival
meta_url_favicon: "https://imgs.search.brave.com/FHqXaNDpskKKJzBVkBH7RgF7kYkNH57EEt1_pz-RnPE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZGQ1NWVjYTY1/ZjYyYWI0OGVmZjdh/N2M3MjZhZDBjZTRj/OWJjMWFkNzNlYWUx/MGU4ZjdmMjRlM2Fj/YTA1NzYyOS9wb3J0/bGFuZGdlcm1hbmZp/bG1mZXN0aXZhbC5j/b20v"
thumbnail: null
extra_snippets: "The economic hardships at the end of the 1920s pushed UFA to the edge of bankruptcy. After the Nazis’ accession to power in 1933, a number of Nazi propaganda films were made under the auspices · of the “Ministry for Public Enlightenment and Propaganda.” Filmmakers such as Josef von Sternberg, Fritz Lang, Ernst Lubitsch, Billy Wilder and stars such as Marlene Dietrich would leave Germany · to try their luck in Hollywood. During this era, the main task of Babelsberg Studios was the production of entertainment films designed to distract German audiences from war-related difficulties.|on, Studio Babelsberg was on Hollywood’s radar, and there was an influx of stars: Kate Winslet, Tom Cruise, George Clooney, Cate Blanchett, Tom Hanks, Bill Murray, Brad Pitt, Diane Kruger, John|IDENTITY, WER IST HANNA?, GRAND BUDAPEST HOTEL, MONUMENTS MEN, THE BOOK THIEF, THE TRIBUTE OF PANEM: MOCKINGJAY, BRIDGE OF SPIES, THE FIRST AVENGER: CIVIL WAR, HOMELAND, A CURE FOR WELLNESS, BERLIN STATION and more. Since 2003, productions completed at Studio Babelsberg have received 48 Academy Award nominations and taken home 15 Oscars in different categories.|On February 12th, 1912, in a glass-house atelier, shooting began on the silent movie DER TOTENTANZ starring Asta Nielsen – thus marking the birth of Studio Babelsberg."
hash: 04886feced6a0b35
embed_ref: portlandgermanfilmfestival.com-Kzn
app_id: web
skill_id: search`,
      parent_embed_id: "4dc639be-e6f2-40a8-99f5-f0dc0884cb4c",
      embed_ids: null,
    },
    {
      embed_id: "bc7c77c1-40a3-4d4c-97c1-300a63af7523",
      type: "website",
      content: `type: search_result
title: Babelsberg Studio — Grokipedia
url: "https://grokipedia.com/page/Babelsberg_Studio"
description: "By 1913, it had developed extensive ... its acquisition by Universum Film AG (UFA) in the 1920s, Babelsberg emerged as the epicenter of German expressionist cinema, producing seminal works such as Nosferatu (1922) and Metropolis ..."
page_age: "January 14, 2026"
profile_name: Grokipedia
meta_url_favicon: "https://imgs.search.brave.com/yYKWPovE0Qx2SH8B50k95Tvf0f00vXHige03xx6em-M/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMGI4ZDVkNDRi/MzU0MjljMTU4Mjk2/ZTA0NWVjNTdlOGM1/NGFiMTM4NWU5OTRl/YjNkMGUxYzZhMGY4/NWJiM2YyOC9ncm9r/aXBlZGlhLmNvbS8"
thumbnail_src: "https://imgs.search.brave.com/Vl0AFa559c2vkKjga2AKIbbfqLlrfd7xg_fasDUqQ0Q/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9ncm9r/aXBlZGlhLmNvbS9w/YWdlL19hc3NldHNf/L0ZpbG1zdHVkaW9f/QmFiZWxzYmVyZ19F/aW5nYW5nLmpwZw"
thumbnail_original: "https://grokipedia.com/page/_assets_/Filmstudio_Babelsberg_Eingang.jpg"
extra_snippets: "Studio Babelsberg has established itself as a primary European hub for Hollywood productions and international co-productions since the studio's privatization in 1992, leveraging its extensive sound stages and backlots to attract major U.S. studios seeking cost efficiencies and technical capabilities unavailable domestically.[32] This shift intensified in the 2000s, with the studio forming strategic alliances such as a 2008 partnership with Hollywood producer Joel Silver to develop feature films from the Dark Castle Entertainment slate, enabling U.S. filmmakers to utilize Babelsberg's infrastr|In the Weimar era, Studio Babelsberg advanced film techniques through innovations like the \\"unchained camera\\" method in the early 1920s, which allowed dynamic perspective shifts, and pioneering special effects in productions such as Metropolis (1927), utilizing miniatures and composite processes to depict futuristic machinery and cityscapes.[47][48] By 1929, the studio constructed the Tonkreuz complex, Europe's first dedicated sound film facility, facilitating the shift to synchronized audio in German cinema.[3][39] During the Nazi period, Babelsberg integrated Agfacolor technology, producing|Collaborations with global platforms such as Netflix, Amazon Prime Video, Disney+, and Hulu have resulted in high-budget series utilizing the studio's infrastructure, including its TV & Media Center with five dedicated stages totaling 43,000 square feet.[66][33] Prominent German-language series produced or filmed there include Babylon Berlin, a period crime drama co-produced by UFA Fiction and Sky, with extensive interior and set filming at the studio across all seasons since its 2017 premiere, recreating 1920s Weimar-era Berlin environments.[67] UFA Fiction, based in Potsdam-Babelsberg, has a|By 1913, it had developed extensive facilities for processing film prints, enabling efficient production cycles that supported the rapid growth of the German film sector during World War I, where films served both entertainment and propaganda purposes.[4][47] In the Weimar Republic era, following its acquisition by Universum Film AG (UFA) in the 1920s, Babelsberg emerged as the epicenter of German expressionist cinema, producing seminal works such as Nosferatu (1922) and Metropolis (1927), which showcased technical innovations like advanced special effects and set design that influenced international filmmakers."
hash: 653764edfd1f0882
embed_ref: grokipedia.com-NNS
app_id: web
skill_id: search`,
      parent_embed_id: "4dc639be-e6f2-40a8-99f5-f0dc0884cb4c",
      embed_ids: null,
    },
    {
      embed_id: "a4f00870-18c2-4c8b-991f-3347e9407e6d",
      type: "website",
      content: `type: search_result
title: "Babelsberg: World's oldest large-scale film studio"
url: "https://www.dw.com/en/babelsberg-worlds-oldest-large-scale-film-studio/g-18416410"
description: "Because the hot spotlights kept triggering fire alarms, they were asked to find a more remote location. Film pioneer Guido Seeber picked new premises in Potsdam-Babelsberg, at the southwest outskirts of Berlin, where a first studio was built in 1911."
page_age: ""
profile_name: DW
meta_url_favicon: "https://imgs.search.brave.com/xZhYJPqD9Ntb1goXRmIlGPu4JZBR3TUSZD8b4LyKCZU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODgzYTI5YzRh/ZGVkZTlkYWMzZjI5/MGY0OGQwOGQ2OGI0/NWQyZWVmYzFkOWJh/MjM4NWNkYTE1NTNl/MjI5MWY2Ny93d3cu/ZHcuY29tLw"
thumbnail_src: "https://imgs.search.brave.com/9xmwIJfnV27xOPKhSV5qH8kjFODl4Cz4ebyizWG1VEA/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zdGF0/aWMuZHcuY29tL2lt/YWdlLzE4NDEzNDI4/XzYuanBn"
thumbnail_original: "https://static.dw.com/image/18413428_6.jpg"
extra_snippets: "While independent US producers were already establishing their studios in Hollywood, German filmmakers were shooting in the center of Berlin. Because the hot spotlights kept triggering fire alarms, they were asked to find a more remote location. Film pioneer Guido Seeber picked new premises in Potsdam-Babelsberg, at the southwest outskirts of Berlin, where a first studio was built in 1911.|In 1922, the German film production company UFA joined in. New techniques were developed: Wilhelm Murnau used a moving camera for the first time in the film \\"The Last Laugh\\" (starring Emil Jannings, pictured here). Hollywood directors came to Babelsberg to learn the newest tricks of the trade.|Berliners might be used to seeing film crews in their city, but they still love to catch a glimpse of their favorite Hollywood stars.Image: picture-alliance/dpa/M. Close · Part of the US television series \\"Homeland\\" was also filmed in Germany. In the fifth season, agent Carrie Mathison (Claire Danes) moves from Kabul to Berlin and works for Germany's intelligence agency. The production's base was not the Federal Intelligence Service's huge offices, but rather the Babelsberg Film Studios.Image: picture alliance/landov|Many American productions have filmed in Babelsberg in recent years, bringing a touch of Hollywood glamour to Potsdam."
hash: a57e88b8516ec8f3
embed_ref: dw.com-duH
app_id: web
skill_id: search`,
      parent_embed_id: "4dc639be-e6f2-40a8-99f5-f0dc0884cb4c",
      embed_ids: null,
    },
    {
      embed_id: "4dc639be-e6f2-40a8-99f5-f0dc0884cb4c",
      type: "app_skill_use",
      content: `app_id: web
skill_id: search
result_count: 6
embed_ids: a207c870-ea93-424d-b702-3b9b4c9ba04c|0a9700c6-4842-4daf-bdca-bb961a33aee6|c8aa3905-8f5b-4b87-8847-e5c9787284ae|4ac7cb99-9b6b-4675-8c61-412c7035414b|bc7c77c1-40a3-4d4c-97c1-300a63af7523|a4f00870-18c2-4c8b-991f-3347e9407e6d
status: finished
query: history of Babelsberg Studio vs Hollywood 1920s
id: 2
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: [
        "a207c870-ea93-424d-b702-3b9b4c9ba04c",
        "0a9700c6-4842-4daf-bdca-bb961a33aee6",
        "c8aa3905-8f5b-4b87-8847-e5c9787284ae",
        "4ac7cb99-9b6b-4675-8c61-412c7035414b",
        "bc7c77c1-40a3-4d4c-97c1-300a63af7523",
        "a4f00870-18c2-4c8b-991f-3347e9407e6d",
      ],
    },
    {
      embed_id: "3f242ede-30f8-44e1-9419-9f832e457982",
      type: "app_skill_use",
      content: `app_id: web
skill_id: search
result_count: 6
embed_ids: 5933cea3-6252-4d5f-b4cb-6b3b5436bb79|39b649ea-c963-4be7-a3a6-dc521610df9b|5816086e-7683-474f-b2c9-41dc4a7873cb|ee18c1ad-830b-497a-b9ce-eb435ae15c96|981f134b-b157-47d9-ad3d-da9024ed82e9|506569b8-3d37-4272-bcbe-afa2dcfd4e43
status: finished
query: German cinema vs Hollywood history 1920s production volume influence
id: 1
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: [
        "5933cea3-6252-4d5f-b4cb-6b3b5436bb79",
        "39b649ea-c963-4be7-a3a6-dc521610df9b",
        "5816086e-7683-474f-b2c9-41dc4a7873cb",
        "ee18c1ad-830b-497a-b9ce-eb435ae15c96",
        "981f134b-b157-47d9-ad3d-da9024ed82e9",
        "506569b8-3d37-4272-bcbe-afa2dcfd4e43",
      ],
    },
    {
      embed_id: "506569b8-3d37-4272-bcbe-afa2dcfd4e43",
      type: "website",
      content: `type: search_result
title: "Forgotten Hollywood: German Cinema of the Weimar Period - Golden Globes"
url: "https://goldenglobes.com/articles/forgotten-hollywood-german-cinema-weimar-period-articles-forgotten-hollywood-german-cinema-weimar-period/"
description: "The movement produced some of the most enduring films of the 1920s and became a heavy influence on Hollywood as well, as many directors eventually emigrated to the US fleeing Nazism."
page_age: "March 25, 2021"
profile_name: Golden Globes
meta_url_favicon: "https://imgs.search.brave.com/aVVys1mA4rktZHIvpXUPEBZY-jAXtgwNmusRjoXe-J0/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZmIwM2Y1ZmI2/NmI4MDIwMmJhZTRl/ZjRlZWQ5NTU0ODll/YmUzYTk1NDkzZDcy/MDk5ZmZhNDY1OTVj/NGNiZDg4Zi9nb2xk/ZW5nbG9iZXMuY29t/Lw"
thumbnail_src: "https://imgs.search.brave.com/8aszWP0Dho5jGFSGxoeemMgg8lsmoQv8H6bKD9b_AzY/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9nb2xk/ZW5nbG9iZXMuY29t/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDIz/LzExL3RoZS1zdHVk/ZW50LW9mLXByYWd1/ZS0xOTEzLmpwZw"
thumbnail_original: "https://goldenglobes.com/wp-content/uploads/2023/11/the-student-of-prague-1913.jpg"
extra_snippets: "Stylized imagery and exaggerated and distorted mise-en-scene to reflect the inner psychology of the characters were the hallmarks of German Expressionism. The stylish beauty of German cinema during the Weimar were influenced by the political and psychological effects of World War I on the minds of German filmmakers, pushing them to take subjectivity to extremes and creating strange expressionistic worlds.|The movement produced some of the most enduring films of the 1920s and became a heavy influence on Hollywood as well, as many directors eventually emigrated to the US fleeing Nazism.|Lubitsch was among the first German directors to emigrate to Hollywood to escape the rise of Nazi rule. In 1919, an independent studio – Decla – produced the breakout film titled Das Kabinett des Dr. Caligari (The Cabinet of Dr. Caligari) that reshaped the German film style and influenced the look and tone of Hollywood genre movies.|But as Germany started to lean towards fascism, many filmmakers fled to London, New York and Hollywood taking the techniques of German expressionism with them. Many Hollywood films like Douglas Sirk’s All That Heaven Allows (1955) shows the deep influence of German expressionism."
hash: 94c885502bf49972
embed_ref: goldenglobes.com-xAB
app_id: web
skill_id: search`,
      parent_embed_id: "3f242ede-30f8-44e1-9419-9f832e457982",
      embed_ids: null,
    },
    {
      embed_id: "981f134b-b157-47d9-ad3d-da9024ed82e9",
      type: "website",
      content: `type: search_result
title: Cinema of the Weimar Republic (1918-1933) | Portland German Film Festival
url: "https://portlandgermanfilmfestival.com/cinema-of-the-weimar-republic-1918-1933/"
description: "At the beginning of this period, in 1919, 470 films were released. In 1920, 510 films were released. At its largest levels of production and output, the German film industry was only second to Hollywood in the number of films produced and released."
page_age: ""
profile_name: Portlandgermanfilmfestival
meta_url_favicon: "https://imgs.search.brave.com/FHqXaNDpskKKJzBVkBH7RgF7kYkNH57EEt1_pz-RnPE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZGQ1NWVjYTY1/ZjYyYWI0OGVmZjdh/N2M3MjZhZDBjZTRj/OWJjMWFkNzNlYWUx/MGU4ZjdmMjRlM2Fj/YTA1NzYyOS9wb3J0/bGFuZGdlcm1hbmZp/bG1mZXN0aXZhbC5j/b20v"
thumbnail: null
extra_snippets: "At the beginning of this period, in 1919, 470 films were released. In 1920, 510 films were released. At its largest levels of production and output, the German film industry was only second to Hollywood in the number of films produced and released.|Caligari (The Cabinet of Dr. Caligari) in 1920. This revolutionary film set the stage for the grand wave of German Expressionist films that would come to define the industry in the 1920s. Ernst Lubitsch came to fame due to his work with historical films like Madame Dubarry (1919).|In a search for foreshadowing of the fascist Nazi regime in German film from the Weimar period, these films have often been brushed aside when looking at the history of German film in favor of many of the darker films of the period. However, these films proved to be especially popular with mass audiences, particularly as filmmakers continued to take cues from Hollywood, which was in a Golden Age of the movie musical.|The Weimar film industry also produced a great number of detective films, many of which influenced the popular film noir of the 1940s and 1950s. Fritz Lang directed the first in a series of films, Dr."
hash: 8dcc54631e062e9c
embed_ref: portlandgermanfilmfestival.com-9XT
app_id: web
skill_id: search`,
      parent_embed_id: "3f242ede-30f8-44e1-9419-9f832e457982",
      embed_ids: null,
    },
    {
      embed_id: "5933cea3-6252-4d5f-b4cb-6b3b5436bb79",
      type: "website",
      content: `type: search_result
title: Weimar cinema
url: "https://alphahistory.com/weimarrepublic/weimar-cinema/"
description: "But post-war American films were more concerned with volume and profit than with art or style. Hollywood churned out around 800 movies a year through the 1920s, mostly lightweight features like slapstick comedies, romantic dramas or swashbuckling ..."
page_age: "October 28, 2023"
profile_name: Alpha History
meta_url_favicon: "https://imgs.search.brave.com/Q6WPfv3x7NUc4B1gBUQtiedUWBEsyqNIG4faJFKE2IQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzg0N2UxYmJj/YTIzMTk5ZTViNTg2/MDQwZmNhNzliZDU5/NjhmMGI5Y2MwMjk2/YTMzNTQxNTA4ZjAx/MTI4MDRkNy9hbHBo/YWhpc3RvcnkuY29t/Lw"
thumbnail_src: "https://imgs.search.brave.com/pEZJzk7Y-Df0D_8vlWC9-UrO4Mk9RsIuLiwqi0LoWLg/rs:fit:200:200:1:0/g:ce/aHR0cDovL2FscGhh/aGlzdG9yeS5jb20v/d2VpbWFycmVwdWJs/aWMvd3AtY29udGVu/dC91cGxvYWRzLzIw/MTIvMDcvbm9zZmVy/YXR1Mi1lMTY5ODUw/MDExMDE2NS5qcGVn"
thumbnail_original: "http://alphahistory.com/weimarrepublic/wp-content/uploads/2012/07/nosferatu2-e1698500110165.jpeg"
extra_snippets: "The political tumult of 1920s Germany helped give rise to a new genre of film-makers: the expressionists of Weimar cinema. Europe’s fledgeling film industry was devastated by World War I, allowing the United States to dominate post-war movie production. But post-war American films were more concerned with volume and profit than with art or style. Hollywood churned out around 800 movies a year through the 1920s, mostly lightweight features like slapstick comedies, romantic dramas or swashbuckling adventure movies.|It was most obvious in the cinema, which recovered quickly in the 1920s, as ordinary Germans sought escapism and cheap entertainment. Unable to afford the huge sets, lavish costumes and extensive props of Hollywood films, German film-makers looked for new ways to convey atmosphere, mood and emotion.|German expressionist cinema would influence film-making around the world – including in the US. In 1923, Hollywood’s Universal Studios produced its first acclaimed horror film, The Hunchback of Notre Dame, starring Lon Chaney as Quasimodo. The director, Wallace Worsley, had previously churned out dozens of dramas and lightweight comedies – but he came to admire and borrow heavily from German directors, particularly Murnau.|They also explored much darker themes than Hollywood: crime, immorality, social decay and the destructive powers of money and technology. German expressionism gave birth to two new cinematic genres: the Gothic horror movie and film noir (crime thrillers which explore the darker aspects of human behaviour). Some of the best known German expressionist films were:"
hash: 0a84de21736ccee8
embed_ref: alphahistory.com-RDW
app_id: web
skill_id: search`,
      parent_embed_id: "3f242ede-30f8-44e1-9419-9f832e457982",
      embed_ids: null,
    },
    {
      embed_id: "ee18c1ad-830b-497a-b9ce-eb435ae15c96",
      type: "website",
      content: `type: search_result
title: "German Cinema, 1920-1930 – Modernism Lab"
url: "https://campuspress.yale.edu/modernismlab/german-cinema-1920-1930/"
description: "Subsequently most of the directors, with the one notable exception of Pabst, left Germany and continued their work in Hollywood. ... Kracauer, Siegfried. From Caligari to Hitler. A Psychological History of German Film. 1947. Princeton: Princeton University Press, 1974. Eisner, Lotte. The Haunted Screen. Expressionism in the German Cinema and the Influence of Max Reinhardt."
page_age: ""
profile_name: Yale Modernism Lab
meta_url_favicon: "https://imgs.search.brave.com/aNiQunGTA0Qu-BEHdhX263rVzktH00-qaXJyveG7scM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMjcxOThhMGJj/NWI0NzQ4YmI0MmQ4/YzdkYmQzZWNjYWZk/MDVhOWExMDcwYmZh/MWRjY2JiZDAxYTAz/NTlmYTMyMC9jYW1w/dXNwcmVzcy55YWxl/LmVkdS8"
thumbnail: null
extra_snippets: "The most prominent German directors from that period, namely Friedrich Wilhelm Murnau, Fritz Lang, and Georg Wilhelm Pabst, made films in the romantic tradition in the early 1920ies, but would turn to the modern branch entirely in the late 1920s. ... The influence of romanticism on early German expressionist cinema can be seen in all parts of filmmaking.|Their genuinely cinematic elements mingle with elements from romanticism and create films that later on influenced whole genres, like the film noir or the horror film. ... However, the commercially successful expressionist branch was short-lived. Already the titles of the most important films from the second half of the 1920s indicate new topics, like for example the growing significance of the city: Pabst’s Die Freudlose Gasse [Joyless Streets] (1925), Lang’s Metropolis (1927), or Walter Ruttmann’s Berlin: Die Symphonie der Großstadt [Berlin: Symphony of a Great City; co-directed by young Samuel ‘Billy’ Wilder] (1927).|Subsequently most of the directors, with the one notable exception of Pabst, left Germany and continued their work in Hollywood. ... Kracauer, Siegfried. From Caligari to Hitler. A Psychological History of German Film. 1947. Princeton: Princeton University Press, 1974. Eisner, Lotte. The Haunted Screen. Expressionism in the German Cinema and the Influence of Max Reinhardt.|The growing of cities, the rise of fascism in Germany, and the very general increase in speed exert their influence on both literature and film: Formal experiments get more radical, as in Alfred Döblin’s Berlin Alexanderplatz (1929) (picturized in 1931 with the screenplay written by Döblin himself), Robert Musil’s Der Mann ohne Eigenschaften (1931), or in Ruttmann’s Symphonie; socio-political and existential questions become more important, as in Erich Kästner’s Fabian, Thomas Mann’s Mario und der Zauberer (1929), Martin Heidegger’s Sein und Zeit (1927) or in Murnau’s Der Letz"
hash: fb53692ca6f5dced
embed_ref: campuspress.yale.edu-LP2
app_id: web
skill_id: search`,
      parent_embed_id: "3f242ede-30f8-44e1-9419-9f832e457982",
      embed_ids: null,
    },
    {
      embed_id: "5816086e-7683-474f-b2c9-41dc4a7873cb",
      type: "website",
      content: `type: search_result
title: "German Cinema Comes to Hollywood: AC in the 1930s"
url: "https://theasc.com/articles/german-cinema-comes-to-hollywood"
description: "Rosher saw working with the German crews as a mutually beneficial exchange, telling AC he “expects to learn as much from the methods there as his fellow workers may gather from American production methods, as practiced by himself while he is in Germany.” The trail of influence between Berlin and Hollywood went both ways, and American Cinematographer was quick to point this out."
page_age: "October 24, 2022"
profile_name: The American Society of Cinematographers
meta_url_favicon: "https://imgs.search.brave.com/gvk2mTVB-yd_0yN8twMgMA4I9HuPQ3wjS8W6djp99bs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjg1NDczNGUy/MzBlN2I2NWVkMmU1/OGI4YTJiMmViODE1/YWY4MjE1NGFlYTE5/NTdjMmQxYTM5N2Vj/OGE5ZTk4MS90aGVh/c2MuY29tLw"
thumbnail_src: "https://imgs.search.brave.com/Cq0GcAE0YqkoEiM-DXtnNvH173P3zv7KP-uDuiRlrek/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9jZG4u/dGhlYXNjLmNvbS9f/aGVhZGVyQ2Fyb3Vz/ZWxJbWFnZS9NZXRy/b3BvbGlzLmpwZw"
thumbnail_original: "https://cdn.theasc.com/_headerCarouselImage/Metropolis.jpg"
extra_snippets: "Freund in 1948 with his Hollywood camera crew. Throughout its history, one of the great characteristics of the American industry has been its ability to adopt and absorb the filmmaking techniques — and filmmakers — that make waves around the world. There is perhaps no greater example of this than the German influence of the 1920s and ’30s.|Rosher saw working with the German crews as a mutually beneficial exchange, telling AC he “expects to learn as much from the methods there as his fellow workers may gather from American production methods, as practiced by himself while he is in Germany.” The trail of influence between Berlin and Hollywood went both ways, and American Cinematographer was quick to point this out.|Lubitsch asserted that everyone in Berlin knew that Hollywood cinematographers were “in a class by themselves.” · Lubitsch (seated) and crew set a shot on Marlene Dietrich for Angel (1937), photographed by Charles B. Lang, Jr. ASC. By the mid-1920s, the growing importance of the German film industry could not be ignored in Hollywood.|While many in Hollywood scoffed at the showiness of cameras positioned on cranes, spinning plates, and zip lines, the unchained camera suddenly became a staple of nearly every major Hollywood film of the late 1920s — especially when Murnau decamped to Fox to make his masterpiece Sunrise (1927)."
hash: 7acd4ba43c7d5578
embed_ref: theasc.com-GbS
app_id: web
skill_id: search`,
      parent_embed_id: "3f242ede-30f8-44e1-9419-9f832e457982",
      embed_ids: null,
    },
    {
      embed_id: "39b649ea-c963-4be7-a3a6-dc521610df9b",
      type: "website",
      content: `type: search_result
title: Cinema of Germany - Wikipedia
url: "https://en.wikipedia.org/wiki/Cinema_of_Germany"
description: "Many up-and-coming German directors also fled to the U.S., having a major influence on American film as a result. A number of the Universal Horror films of the 1930s were directed by German emigrees, including Karl Freund, Joe May and Robert Siodmak."
page_age: 3 weeks ago
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/2bxv63p9XD1LlDj_j53N29drxKNwSHB8TimiGIobP28/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvZW4vMC8wOC9T/Y2hyZWNrLmpwZw"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/en/0/08/Schreck.jpg"
extra_snippets: "The Expressionist movement began to wane during the mid-1920s, but perhaps the fact that its main creators moved to Hollywood, California, allowed this style to remain influential in world cinema for years to come, particularly in American horror films and film noir and in the works of European directors such as Jean Cocteau and Ingmar Bergman.|Film historian Lotte Eisner argues that the Expressionist style was deeply influenced by German Romanticism and by innovations of director Max Reinhardt, whose emphasis on atmosphere and lighting shaped the visuals of early cinema. Siegfried Kracauer similarly interpreted Weimar films as reflections of the nation’s collective psychological state. In From Caligari to Hitler, he emphasizes the recurring themes of authority, fear, and disorder shown in films of the 1920s revealed the underlying fears that later contributed to the rise of authoritarian politics in Germany.|UFA showed an interest, but possibly due to financial difficulties, never made a sound film. But in the late 1920s, sound production and distribution were starting to be adopted by the German film industry and by 1932 Germany had 3,800 cinemas equipped to play sound films.|Many up-and-coming German directors also fled to the U.S., having a major influence on American film as a result. A number of the Universal Horror films of the 1930s were directed by German emigrees, including Karl Freund, Joe May and Robert Siodmak. Directors Edgar Ulmer and Douglas Sirk and the Austrian-born screenwriter (and later director) Billy Wilder also emigrated from Nazi Germany to Hollywood success.|In addition, a distinction is sometimes drawn between the avantgarde \\"Young German Cinema\\" of the 1960s and the more accessible \\"New German Cinema\\" of the 1970s. For their influences the new generation of film-makers looked to Italian neorealism, the French Nouvelle Vague and the British New Wave but combined this eclectically with references to the well-established genres of Hollywood cinema."
hash: 0e69017a321f054d
embed_ref: en.wikipedia.org-jka
app_id: web
skill_id: search`,
      parent_embed_id: "3f242ede-30f8-44e1-9419-9f832e457982",
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 7,
  },
};
