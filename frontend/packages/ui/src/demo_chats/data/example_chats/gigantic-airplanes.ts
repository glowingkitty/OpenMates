// frontend/packages/ui/src/demo_chats/data/example_chats/gigantic-airplanes.ts
//
// Example chat: Gigantic airplanes for transporting rocket and airplane parts
// Extracted from shared chat b5b913ad-0afd-41be-b630-5b33ce23367a
//
// This is a real conversation showcasing web search, image search, and
// knowledge retrieval about specialized cargo aircraft (An-225, Super Guppy, BelugaXL).

import type { ExampleChat } from "../../types";

export const giganticAirplanesChat: ExampleChat = {
  chat_id: "example-gigantic-airplanes",
  slug: "gigantic-airplanes-transporting-rocket-parts",
  title: "example_chats.gigantic_airplanes.title",
  summary: "example_chats.gigantic_airplanes.summary",
  icon: "plane",
  category: "general_knowledge",
  keywords: [
    "cargo aircraft", "rocket transport", "An-225 Mriya", "Super Guppy",
    "BelugaXL", "Airbus Beluga", "airplane parts transport", "oversized cargo",
    "aviation", "space logistics"
  ],
  follow_up_suggestions: [
    "example_chats.gigantic_airplanes.follow_up_1",
    "example_chats.gigantic_airplanes.follow_up_2",
    "example_chats.gigantic_airplanes.follow_up_3",
    "example_chats.gigantic_airplanes.follow_up_4",
    "example_chats.gigantic_airplanes.follow_up_5",
    "example_chats.gigantic_airplanes.follow_up_6"
  ],
  messages: [
    {
      id: "33ce23367a-ea8b83bf-c9c3-4c19-ad45-100a067eb6e8",
      role: "user",
      content: "example_chats.gigantic_airplanes.user_message_1",
      created_at: 1775940845,
      category: "general_knowledge",
    },
    {
      id: "5f815be6-96ef-42c6-a4aa-1b07a2840a16",
      role: "assistant",
      content: `\`\`\`json
{"type": "app_skill_use", "embed_id": "c71ba783-237b-4f89-8034-a44bd560fe65", "app_id": "web", "skill_id": "search", "query": "gigantic airplane used to transport rocket parts name", "provider": "Brave"}
\`\`\`

\`\`\`json
{"type": "app_skill_use", "embed_id": "a9f61cd9-09d1-4010-b720-fc60fe92e0c0", "app_id": "images", "skill_id": "search", "query": "Antonov An-225 Mriya rocket transport", "provider": "Brave"}
\`\`\`

\`\`\`json
{"type": "app_skill_use", "embed_id": "5e183917-41a3-45f4-a0e7-e01e346b1e58", "app_id": "images", "skill_id": "search", "query": "NASA Super Guppy rocket transport", "provider": "Brave"}
\`\`\`

\`\`\`json
{"type": "app_skill_use", "embed_id": "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e", "app_id": "images", "skill_id": "search", "query": "Stratolaunch Roc rocket transport", "provider": "Brave"}
\`\`\`

There are a few "gigantic" airplanes famous for transporting rockets and their components. Depending on whether you mean a plane that carries parts inside it or one that carries a whole shuttle on its back, you are likely thinking of one of these:

### 1. Antonov An-225 Mriya
The **Antonov An-225 Mriya** was the heaviest aircraft ever built and had the largest wingspan of any aircraft in operational service. It was originally designed by the Soviet Union in the 1980s specifically to transport the **Buran space shuttle** and components of the **Energia rocket** on its back. 

[!](embed:popularmechanics.com-kIm)
[!](embed:britannica.com-f9U)
[!](embed:space.com-EES)

### 2. NASA Super Guppy
If you mean the bulbous, strangely-shaped plane that "swallows" rocket parts, that is the **NASA Super Guppy**. It is used by NASA to transport oversized cargo, such as the **S-IVB stage of the Saturn V rocket** during the Apollo era and, more recently, components for the **Artemis** moon missions. Its nose hinges open to allow massive parts to be loaded directly into its fuselage.

[!](embed:interestingengineering.com-fne)
[!](embed:nasa.gov-IKy)
[!](embed:reddit.com-eHx)

### 3. Stratolaunch "Roc"
The **Stratolaunch Roc** currently holds the record for the world's longest wingspan (385 feet). Unlike the others, it is designed as a **mobile launch platform** to carry rockets to high altitudes between its twin fuselages and release them into space.

[!](embed:jetsprops.com-uun)
[!](embed:cnet.com-ML7)
[!](embed:jetsprops.com-opu)

**Which one looks most like the one you saw?**
- The **An-225** (Soviet/Ukrainian) is a massive six-engine jet.
- The **Super Guppy** (NASA) looks like a giant, inflated whale.
- The **Stratolaunch** has two separate bodies (twin-fuselage).

Would you like to know more about the history of the [An-225 Mriya](https://en.wikipedia.org/wiki/Antonov_An-225_Mriya) or how the [Super Guppy](https://www.nasa.gov/centers/johnson/flights/guppy.html) works?`,
      created_at: 1775940854,
      category: "general_knowledge",
      model_name: "Gemini 3 Flash",
    },
    {
      id: "33ce23367a-de246a22-3cd4-4770-a6d9-8d0cb38ae83a",
      role: "user",
      content: "example_chats.gigantic_airplanes.user_message_2",
      created_at: 1775947243,
    },
    {
      id: "8bc07ada-624f-4249-99c3-a4643f9b887f",
      role: "assistant",
      content: `\`\`\`json
{"type": "app_skill_use", "embed_id": "040ef265-5dc8-4512-b443-b52bc86f7a6b", "app_id": "web", "skill_id": "search", "query": "Airbus Beluga and BelugaXL history and usage Europe airplane parts", "provider": "Brave"}
\`\`\`

\`\`\`json
{"type": "app_skill_use", "embed_id": "f483e089-ff31-472e-9b0d-28f03b92eee1", "app_id": "images", "skill_id": "search", "query": "Airbus BelugaXL transporting airplane parts", "provider": "Brave"}
\`\`\`

\`\`\`json
{"type": "app_skill_use", "embed_id": "893f5c33-f98b-46e7-b81a-475a94827b35", "app_id": "images", "skill_id": "search", "query": "Airbus Beluga A300-600ST vs BelugaXL A330-743L", "provider": "Brave"}
\`\`\`

Yes, you're exactly right! Airbus used the original NASA-style **Super Guppies** until the 1990s, but they eventually built their own specialized versions to transport massive wings and fuselage sections between their factories across Europe.

The aircraft you are thinking of is the **Airbus Beluga**. There are two generations:

### 1. Airbus BelugaST (The Original)
Introduced in 1995, the **BelugaST** (Super Transporter) was based on the Airbus A300-600. It was designed specifically to replace the aging Super Guppy fleet. For nearly 30 years, it was the workhorse that connected Airbus production sites in France, Germany, the UK, and Spain.

[!](embed:airbus.com-lTo)
[!](embed:aviationa2z.com-fNJ)

### 2. Airbus BelugaXL (The New Version)
The "new version" you mentioned is the **BelugaXL**, which entered service in 2020. Based on the much larger **Airbus A330**, it was built to keep up with the production of the A350 jetliner. 
* **Capacity:** It can carry **two A350 wings** at once, whereas the original Beluga could only carry one.
* **The "Smile":** It is famous for its "smiling whale" livery, which was chosen by Airbus employees in a company-wide vote.

[!](embed:cnn.com-5jh)
[!](embed:simpleflying.com-N3v)
[!](embed:gettyimages.com-8Kw)

### Why are they used?
Airbus builds different parts of its planes in different countries (e.g., wings in the UK, tails in Spain, fuselages in Germany). Because these parts are too large to fit on trains or standard cargo planes, the Beluga "swallows" them through a massive front-opening door and flies them to final assembly lines in **Toulouse, France**, or **Hamburg, Germany**.

Would you like to see a [video of how they load a wing](https://www.youtube.com/results?search_query=airbus+belugaxl+loading+wing) into the BelugaXL, or are you interested in how it compares to Boeing's version, the [Dreamlifter](https://en.wikipedia.org/wiki/Boeing_Dreamlifter)?`,
      created_at: 1775947248,
      category: "general_knowledge",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "f6e23f0a-b0cf-4248-8fed-8d02cdc78dac",
      type: "image_result",
      content: `type: image_result
title: "Transporting parts: The Beluga’s main job for almost two decades was to ferry parts of other Airbus aircraft across the company’s various European facilities."
source_page_url: "https://www.cnn.com/travel/airbus-beluga-gets-own-airline"
image_url: "https://media.cnn.com/api/v1/images/stellar/prod/belugaxl-first-flight-low-pass.jpg?c=original&q=h_447,c_fill"
thumbnail_url: "https://imgs.search.brave.com/YW4moaXUYglsNAwZfHL7TTmP1Wdh-FAo6BVnpecLPow/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5jbm4uY29tL2Fw/aS92MS9pbWFnZXMv/c3RlbGxhci9wcm9k/L2JlbHVnYXhsLWZp/cnN0LWZsaWdodC1s/b3ctcGFzcy5qcGc_/Yz1vcmlnaW5hbCZx/PWhfNDQ3LGNfZmls/bA"
source: cnn.com
favicon_url: "https://imgs.search.brave.com/tV1joo3SHuITYemc5OsCps2_N9Toz6zArm5dNdbSoMs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNWE3MWZjOTZk/NGRhM2RmZDQzMjZh/NjE3OGQ3NzQ3MDI5/NDJiOGI2ZDdkZDFj/ODI3N2MzYWU3OGU4/YzQ3YTNkNC93d3cu/Y25uLmNvbS8"
hash: adc92143fb2223c6
embed_ref: cnn.com-5jh
app_id: images
skill_id: search`,
      parent_embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      embed_ids: null,
    },
    {
      embed_id: "a5fcc797-b8d1-4851-89c1-2a4b99e7f65b",
      type: "image_result",
      content: `type: image_result
title: "An Airbus A330-743L Beluga XL is taking off from Toulouse Blagnac Airport in Toulouse, France, on December 5, 2023."
source_page_url: "https://www.gettyimages.com/photos/airbus-beluga"
image_url: "https://media.gettyimages.com/id/1836062561/photo/an-airbus-a330-743l-beluga-xl-is-taking-off-from-toulouse-blagnac-airport-in-toulouse-france.jpg?s=612x612&w=0&k=20&c=Lj0eTANCpqu_7p40b5uFYL9xKuS5ez1J4btfrly-eEA="
thumbnail_url: "https://imgs.search.brave.com/2eFSOV97MHxiwYkpTeNUT8_biyD_khr2ry1fg8pzvNs/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5nZXR0eWltYWdl/cy5jb20vaWQvMTgz/NjA2MjU2MS9waG90/by9hbi1haXJidXMt/YTMzMC03NDNsLWJl/bHVnYS14bC1pcy10/YWtpbmctb2ZmLWZy/b20tdG91bG91c2Ut/YmxhZ25hYy1haXJw/b3J0LWluLXRvdWxv/dXNlLWZyYW5jZS5q/cGc_cz02MTJ4NjEy/Jnc9MCZrPTIwJmM9/TGowZVRBTkNwcXVf/N3A0MGI1dUZZTDl4/S3VTNWV6MUo0YnRm/cmx5LWVFQT0"
source: gettyimages.com
favicon_url: "https://imgs.search.brave.com/pi_-iHcSZ0f3mXMHIzy40iW0l1FZzm1LsS3d544QqYs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODc0ZTlhMjY4/MTM3N2MyZmQwMTNk/MmI0Y2UwMDUxMjM1/YjRlNDYyM2VkYmVl/NDk3MTUwOWI2Nzk0/MDZmMmZlYi93d3cu/Z2V0dHlpbWFnZXMu/Y29tLw"
hash: 96882a4c38647467
embed_ref: gettyimages.com-A98
app_id: images
skill_id: search`,
      parent_embed_id: "893f5c33-f98b-46e7-b81a-475a94827b35",
      embed_ids: null,
    },
    {
      embed_id: "c06a917a-0d9f-4d1c-b573-72e3823ef268",
      type: "image_result",
      content: `type: image_result
title: A set of Airbus A350 XWB wings being loaded into an Airbus BelugaXL aircraft.
source_page_url: "https://simpleflying.com/airbus-beluga-xl-why/"
image_url: "https://static0.simpleflyingimages.com/wordpress/wp-content/uploads/2023/10/belugaxl-first-flight-with-set-of-a350-xwb-wings-1.jpg?q=50&fit=crop&w=825&dpr=1.5"
thumbnail_url: "https://imgs.search.brave.com/uDnCVwQ-zlkYRjV4RMamE4a9FHZLlxtTNkSXUtRZ7yU/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9zdGF0/aWMwLnNpbXBsZWZs/eWluZ2ltYWdlcy5j/b20vd29yZHByZXNz/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDIz/LzEwL2JlbHVnYXhs/LWZpcnN0LWZsaWdo/dC13aXRoLXNldC1v/Zi1hMzUwLXh3Yi13/aW5ncy0xLmpwZz9x/PTUwJmZpdD1jcm9w/Jnc9ODI1JmRwcj0x/LjU"
source: simpleflying.com
favicon_url: "https://imgs.search.brave.com/VMQLlOIvBT3gsq5BXX5pTGGXEXcs37fApdqzYAnDJCU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzljZjhiMmE3/ZDkwMWJiMmEwNjY2/ZTVlYWM0NTk2Mjk2/MzUwODcwMDNiZDE3/MTdmODg5MDBmY2Iw/MzM2NGIwZC9zaW1w/bGVmbHlpbmcuY29t/Lw"
hash: 6575334ba772b9b6
embed_ref: simpleflying.com-N3v
app_id: images
skill_id: search`,
      parent_embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      embed_ids: null,
    },
    {
      embed_id: "673f674f-027b-4d9d-8f06-494caa0f48ba",
      type: "image_result",
      content: `type: image_result
title: "Airbus A330-743L Beluga XL1 takes off from Toulouse Blagnac Airport in Toulouse, France, on June 24, 2025."
source_page_url: "https://www.gettyimages.com/photos/airbus-beluga"
image_url: "https://media.gettyimages.com/id/2221611743/photo/airbus-a330-743l-beluga-xl1-takes-off-from-toulouse-blagnac-airport-in-toulouse-france-on.jpg?s=612x612&w=0&k=20&c=lN_zgOcRF0rse-_d_rESnW5sLn9wbFQXGh5nzCpipds="
thumbnail_url: "https://imgs.search.brave.com/ycEyHUDHx22lNYLTCCcuobEZxEpMWEGY-kczjTAkQpY/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5nZXR0eWltYWdl/cy5jb20vaWQvMjIy/MTYxMTc0My9waG90/by9haXJidXMtYTMz/MC03NDNsLWJlbHVn/YS14bDEtdGFrZXMt/b2ZmLWZyb20tdG91/bG91c2UtYmxhZ25h/Yy1haXJwb3J0LWlu/LXRvdWxvdXNlLWZy/YW5jZS1vbi5qcGc_/cz02MTJ4NjEyJnc9/MCZrPTIwJmM9bE5f/emdPY1JGMHJzZS1f/ZF9yRVNuVzVzTG45/d2JGUVhHaDVuekNw/aXBkcz0"
source: gettyimages.com
favicon_url: "https://imgs.search.brave.com/pi_-iHcSZ0f3mXMHIzy40iW0l1FZzm1LsS3d544QqYs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODc0ZTlhMjY4/MTM3N2MyZmQwMTNk/MmI0Y2UwMDUxMjM1/YjRlNDYyM2VkYmVl/NDk3MTUwOWI2Nzk0/MDZmMmZlYi93d3cu/Z2V0dHlpbWFnZXMu/Y29tLw"
hash: b28996e821fbf61b
embed_ref: gettyimages.com-r4r
app_id: images
skill_id: search`,
      parent_embed_id: "893f5c33-f98b-46e7-b81a-475a94827b35",
      embed_ids: null,
    },
    {
      embed_id: "aa6fdc2c-2c46-44f0-a7b6-28a5517c5cea",
      type: "image_result",
      content: `type: image_result
title: "An Airbus A330-743L Beluga XL is landing at Toulouse Blagnac Airport in Toulouse, France, on December 5, 2023."
source_page_url: "https://www.gettyimages.com/photos/airbus-beluga"
image_url: "https://media.gettyimages.com/id/1836062137/photo/an-airbus-a330-743l-beluga-xl-is-landing-at-toulouse-blagnac-airport-in-toulouse-france-on.jpg?s=612x612&w=0&k=20&c=2vN1-Osk6GuXjEkb9CbGEd4ugT3TJMkkgvgxNpVD_a4="
thumbnail_url: "https://imgs.search.brave.com/yDFoklhqQgqlSDrr3pwWyRb2toI-Irq0mAz-IchVMnE/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5nZXR0eWltYWdl/cy5jb20vaWQvMTgz/NjA2MjEzNy9waG90/by9hbi1haXJidXMt/YTMzMC03NDNsLWJl/bHVnYS14bC1pcy1s/YW5kaW5nLWF0LXRv/dWxvdXNlLWJsYWdu/YWMtYWlycG9ydC1p/bi10b3Vsb3VzZS1m/cmFuY2Utb24uanBn/P3M9NjEyeDYxMiZ3/PTAmaz0yMCZjPTJ2/TjEtT3NrNkd1WGpF/a2I5Q2JHRWQ0dWdU/M1RKTWtrZ3ZneE5w/VkRfYTQ9"
source: gettyimages.com
favicon_url: "https://imgs.search.brave.com/pi_-iHcSZ0f3mXMHIzy40iW0l1FZzm1LsS3d544QqYs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODc0ZTlhMjY4/MTM3N2MyZmQwMTNk/MmI0Y2UwMDUxMjM1/YjRlNDYyM2VkYmVl/NDk3MTUwOWI2Nzk0/MDZmMmZlYi93d3cu/Z2V0dHlpbWFnZXMu/Y29tLw"
hash: 6b14bd30939cba5f
embed_ref: gettyimages.com-lwu
app_id: images
skill_id: search`,
      parent_embed_id: "893f5c33-f98b-46e7-b81a-475a94827b35",
      embed_ids: null,
    },
    {
      embed_id: "799ba3d4-e06b-486f-a745-2460ac581d41",
      type: "image_result",
      content: `type: image_result
title: "The Airbus A330-743L Beluga XL 6 lands at Toulouse Blagnac Airport in Toulouse, France, on June 24, 2025."
source_page_url: "https://www.gettyimages.com/photos/airbus-beluga"
image_url: "https://media.gettyimages.com/id/2221961216/photo/the-airbus-a330-743l-beluga-xl-6-lands-at-toulouse-blagnac-airport-in-toulouse-france-on-june.jpg?s=612x612&w=0&k=20&c=Z2qLqpSx2V67TXk-sgq6LOX32xUdQFWqFzjkj6XMcCk="
thumbnail_url: "https://imgs.search.brave.com/alq3FzU7PMny4RRR7aAoh-JDtCrz22f53cMTgb_7PNk/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5nZXR0eWltYWdl/cy5jb20vaWQvMjIy/MTk2MTIxNi9waG90/by90aGUtYWlyYnVz/LWEzMzAtNzQzbC1i/ZWx1Z2EteGwtNi1s/YW5kcy1hdC10b3Vs/b3VzZS1ibGFnbmFj/LWFpcnBvcnQtaW4t/dG91bG91c2UtZnJh/bmNlLW9uLWp1bmUu/anBnP3M9NjEyeDYx/MiZ3PTAmaz0yMCZj/PVoycUxxcFN4MlY2/N1RYay1zZ3E2TE9Y/MzJ4VWRRRldxRnpq/a2o2WE1jQ2s9"
source: gettyimages.com
favicon_url: "https://imgs.search.brave.com/pi_-iHcSZ0f3mXMHIzy40iW0l1FZzm1LsS3d544QqYs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODc0ZTlhMjY4/MTM3N2MyZmQwMTNk/MmI0Y2UwMDUxMjM1/YjRlNDYyM2VkYmVl/NDk3MTUwOWI2Nzk0/MDZmMmZlYi93d3cu/Z2V0dHlpbWFnZXMu/Y29tLw"
hash: f6a0506f4ef17e66
embed_ref: gettyimages.com-8Kw
app_id: images
skill_id: search`,
      parent_embed_id: "893f5c33-f98b-46e7-b81a-475a94827b35",
      embed_ids: null,
    },
    {
      embed_id: "893f5c33-f98b-46e7-b81a-475a94827b35",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 799ba3d4-e06b-486f-a745-2460ac581d41|a5fcc797-b8d1-4851-89c1-2a4b99e7f65b|aa6fdc2c-2c46-44f0-a7b6-28a5517c5cea|adfd6894-6fcb-4047-8204-db7aefb0dd11|673f674f-027b-4d9d-8f06-494caa0f48ba|33170274-e832-4854-a319-12ac02171225
status: finished
query: Airbus Beluga A300-600ST vs BelugaXL A330-743L
id: 2
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["799ba3d4-e06b-486f-a745-2460ac581d41", "a5fcc797-b8d1-4851-89c1-2a4b99e7f65b", "aa6fdc2c-2c46-44f0-a7b6-28a5517c5cea", "adfd6894-6fcb-4047-8204-db7aefb0dd11", "673f674f-027b-4d9d-8f06-494caa0f48ba", "33170274-e832-4854-a319-12ac02171225"],
    },
    {
      embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: f6e23f0a-b0cf-4248-8fed-8d02cdc78dac|54d7a815-ce47-4954-b3b6-d7e13216ccd4|ae35c30c-be3a-43c4-8bb3-395876b9f732|c06a917a-0d9f-4d1c-b573-72e3823ef268|61c021b2-9c97-4b8e-9107-9455004a8e48|09434ad0-0fed-4414-beea-809d0b7a0ff4
status: finished
query: Airbus BelugaXL transporting airplane parts
id: 1
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["f6e23f0a-b0cf-4248-8fed-8d02cdc78dac", "54d7a815-ce47-4954-b3b6-d7e13216ccd4", "ae35c30c-be3a-43c4-8bb3-395876b9f732", "c06a917a-0d9f-4d1c-b573-72e3823ef268", "61c021b2-9c97-4b8e-9107-9455004a8e48", "09434ad0-0fed-4414-beea-809d0b7a0ff4"],
    },
    {
      embed_id: "ae35c30c-be3a-43c4-8bb3-395876b9f732",
      type: "image_result",
      content: `type: image_result
title: "Airbus Beluga XL or BelugaXL, renowned as the world's largest cargo aircraft, touched down at Netaji Subhash Chandra Bose International Airport (CCU) in Kolkata"
source_page_url: "https://aviationa2z.com/index.php/2024/10/14/airbus-belugaxl-returns-to-kolkata-airport/"
image_url: "https://aviationa2z.com/wp-content/uploads/2023/07/image-212-1024x683.png"
thumbnail_url: "https://imgs.search.brave.com/YDKOQ4Ga97Ne6CIUJ4dmYOjWCuNUSgzCSGOOlP5RsW0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9hdmlh/dGlvbmEyei5jb20v/d3AtY29udGVudC91/cGxvYWRzLzIwMjMv/MDcvaW1hZ2UtMjEy/LTEwMjR4NjgzLnBu/Zw"
source: aviationa2z.com
favicon_url: "https://imgs.search.brave.com/0CT-CiJ1TRWq6dNBtCC2j_XTBGc9U_k6TwErY5n-FkE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMmUzYjYzNzEw/NWI0MTdiODVmNmRj/NTFmNjI2MjRiMTYx/YjZhNTNlOWY3OWRh/NzdjOWMwYTRkMDEw/M2UyNTU4MC9hdmlh/dGlvbmEyei5jb20v"
hash: 71783cd8d576d649
embed_ref: aviationa2z.com-B7A
app_id: images
skill_id: search`,
      parent_embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      embed_ids: null,
    },
    {
      embed_id: "54d7a815-ce47-4954-b3b6-d7e13216ccd4",
      type: "image_result",
      content: `type: image_result
title: "Airbus is trying to find a new home for its Airbus Beluga, but transporting these cargo planes isn't easy"
source_page_url: "https://supercarblondie.com/airbus-beluga-cargo-plane-storage-nightmare/"
image_url: "https://supercarblondie.com/wp-content/uploads/Airbus-Beluga-and-BelugaXL-1024x640.webp"
thumbnail_url: "https://imgs.search.brave.com/OsQblfE5r2WBBRTz2S3UD5xV2Q7SC4AA5vqmRPlwzrs/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9zdXBl/cmNhcmJsb25kaWUu/Y29tL3dwLWNvbnRl/bnQvdXBsb2Fkcy9B/aXJidXMtQmVsdWdh/LWFuZC1CZWx1Z2FY/TC0xMDI0eDY0MC53/ZWJw"
source: supercarblondie.com
favicon_url: "https://imgs.search.brave.com/7nD42lYV6sbIvSZ0gGfVjxSM2XQKyu-fjdPD6i-xFpc/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGRhZGZhMDQ5/NWU5NTY1ZGQ5YWJi/OTJlOTg2MjIxMmI3/OWExZTJiY2IwZTc2/NzFiNzNiZDU2OTM4/YzhmOTc2OS9zdXBl/cmNhcmJsb25kaWUu/Y29tLw"
hash: 3e21180b7573e196
embed_ref: supercarblondie.com-UCM
app_id: images
skill_id: search`,
      parent_embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      embed_ids: null,
    },
    {
      embed_id: "09434ad0-0fed-4414-beea-809d0b7a0ff4",
      type: "image_result",
      content: `type: image_result
title: Two Airbus BelugaXL airlifters parked at an airport.
source_page_url: "https://simpleflying.com/boeing-dreamlifter-vs-airbus-beluga-xl/"
image_url: "https://static0.simpleflyingimages.com/wordpress/wp-content/uploads/2022/10/Airbus_-first-two-BelugaXL-airlifters.jpg?q=50&fit=crop&w=825&dpr=1.5"
thumbnail_url: "https://imgs.search.brave.com/f4wPwQfG-Q074QCj3Al8o6JjjZZCWBB0Ur-OI_grGYI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9zdGF0/aWMwLnNpbXBsZWZs/eWluZ2ltYWdlcy5j/b20vd29yZHByZXNz/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDIy/LzEwL0FpcmJ1c18t/Zmlyc3QtdHdvLUJl/bHVnYVhMLWFpcmxp/ZnRlcnMuanBnP3E9/NTAmZml0PWNyb3Am/dz04MjUmZHByPTEu/NQ"
source: simpleflying.com
favicon_url: "https://imgs.search.brave.com/VMQLlOIvBT3gsq5BXX5pTGGXEXcs37fApdqzYAnDJCU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzljZjhiMmE3/ZDkwMWJiMmEwNjY2/ZTVlYWM0NTk2Mjk2/MzUwODcwMDNiZDE3/MTdmODg5MDBmY2Iw/MzM2NGIwZC9zaW1w/bGVmbHlpbmcuY29t/Lw"
hash: e6c271f50fe4476a
embed_ref: simpleflying.com-mdY
app_id: images
skill_id: search`,
      parent_embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      embed_ids: null,
    },
    {
      embed_id: "61c021b2-9c97-4b8e-9107-9455004a8e48",
      type: "image_result",
      content: `type: image_result
title: "Airbus Beluga XL or BelugaXL, renowned as the world's largest cargo aircraft, touched down at Netaji Subhash Chandra Bose International Airport (CCU) in Kolkata"
source_page_url: "https://aviationa2z.com/index.php/2024/10/14/airbus-belugaxl-returns-to-kolkata-airport/"
image_url: "https://aviationa2z.com/wp-content/uploads/2023/06/1080px-F-GSTB_-_2_Airbus_A300B4-608ST_Beluga_Airbus_8634655670-1024x683.jpg"
thumbnail_url: "https://imgs.search.brave.com/00ktijbQMsLfb-AzJLVtk1w9YNgjiCUxCX95PQRKbhQ/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9hdmlh/dGlvbmEyei5jb20v/d3AtY29udGVudC91/cGxvYWRzLzIwMjMv/MDYvMTA4MHB4LUYt/R1NUQl8tXzJfQWly/YnVzX0EzMDBCNC02/MDhTVF9CZWx1Z2Ff/QWlyYnVzXzg2MzQ2/NTU2NzAtMTAyNHg2/ODMuanBn"
source: aviationa2z.com
favicon_url: "https://imgs.search.brave.com/0CT-CiJ1TRWq6dNBtCC2j_XTBGc9U_k6TwErY5n-FkE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMmUzYjYzNzEw/NWI0MTdiODVmNmRj/NTFmNjI2MjRiMTYx/YjZhNTNlOWY3OWRh/NzdjOWMwYTRkMDEw/M2UyNTU4MC9hdmlh/dGlvbmEyei5jb20v"
hash: cbe33bd1060f1fbc
embed_ref: aviationa2z.com-fNJ
app_id: images
skill_id: search`,
      parent_embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      embed_ids: null,
    },
    {
      embed_id: "f6e23f0a-b0cf-4248-8fed-8d02cdc78dac",
      type: "image_result",
      content: `type: image_result
title: "Transporting parts: The Beluga’s main job for almost two decades was to ferry parts of other Airbus aircraft across the company’s various European facilities."
source_page_url: "https://www.cnn.com/travel/airbus-beluga-gets-own-airline"
image_url: "https://media.cnn.com/api/v1/images/stellar/prod/belugaxl-first-flight-low-pass.jpg?c=original&q=h_447,c_fill"
thumbnail_url: "https://imgs.search.brave.com/YW4moaXUYglsNAwZfHL7TTmP1Wdh-FAo6BVnpecLPow/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5jbm4uY29tL2Fw/aS92MS9pbWFnZXMv/c3RlbGxhci9wcm9k/L2JlbHVnYXhsLWZp/cnN0LWZsaWdodC1s/b3ctcGFzcy5qcGc_/Yz1vcmlnaW5hbCZx/PWhfNDQ3LGNfZmls/bA"
source: cnn.com
favicon_url: "https://imgs.search.brave.com/tV1joo3SHuITYemc5OsCps2_N9Toz6zArm5dNdbSoMs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNWE3MWZjOTZk/NGRhM2RmZDQzMjZh/NjE3OGQ3NzQ3MDI5/NDJiOGI2ZDdkZDFj/ODI3N2MzYWU3OGU4/YzQ3YTNkNC93d3cu/Y25uLmNvbS8"
hash: adc92143fb2223c6
embed_ref: cnn.com-5jh
app_id: images
skill_id: search`,
      parent_embed_id: "f483e089-ff31-472e-9b0d-28f03b92eee1",
      embed_ids: null,
    },
    {
      embed_id: "33170274-e832-4854-a319-12ac02171225",
      type: "image_result",
      content: `type: image_result
title: "Airbus A330-700 Beluga XL2, August 27, 2021"
source_page_url: "https://www.airlinerspotter.com/airbus-beluga.htm"
image_url: "https://airlinerspotter.com/images/contributors/edel/Airbus%20A330-700%20XL3%20F-GXLI%20LFLX%20le%20August%20of%202021.jpg"
thumbnail_url: "https://imgs.search.brave.com/KD1xGsccH3b_peb9tMcB_0yyPzG45xAyCRSn1RexYYQ/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9haXJs/aW5lcnNwb3R0ZXIu/Y29tL2ltYWdlcy9j/b250cmlidXRvcnMv/ZWRlbC9BaXJidXMl/MjBBMzMwLTcwMCUy/MFhMMyUyMEYtR1hM/SSUyMExGTFglMjBs/ZSUyMEF1Z3VzdCUy/MG9mJTIwMjAyMS5q/cGc"
source: airlinerspotter.com
favicon_url: "https://imgs.search.brave.com/HWNwWsvjcw8WOlSNzPbOQ8JFYfqMBaDr_Hs9kAiB3i4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYmU4NTg0N2Yz/ZjBlMTY1Zjk3MWE5/NTlhMTZkOGM4ZWU1/NTk0M2UzMTQ5MzVj/NTFjODBlODQ0OGFi/OTE4MGM5OC93d3cu/YWlybGluZXJzcG90/dGVyLmNvbS8"
hash: 913804fa57e0fd3a
embed_ref: airlinerspotter.com-rj9
app_id: images
skill_id: search`,
      parent_embed_id: "893f5c33-f98b-46e7-b81a-475a94827b35",
      embed_ids: null,
    },
    {
      embed_id: "adfd6894-6fcb-4047-8204-db7aefb0dd11",
      type: "image_result",
      content: `type: image_result
title: "airbus belugaxl a330-743l taxiing out to the runway - airbus beluga stock pictures, royalty-free photos & images"
source_page_url: "https://www.gettyimages.com/photos/airbus-beluga"
image_url: "https://media.gettyimages.com/id/2182065132/photo/airbus-belugaxl-a330-743l-taxiing-out-to-the-runway.jpg?s=612x612&w=0&k=20&c=7WatHROx6rgTqqwMpRS6uHTz4af7aa-UlhMA4MNVWEM="
thumbnail_url: "https://imgs.search.brave.com/LJJwOMxchaFtPOvo2N5sh8hPJTkWETyMF088DJueTmE/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5nZXR0eWltYWdl/cy5jb20vaWQvMjE4/MjA2NTEzMi9waG90/by9haXJidXMtYmVs/dWdheGwtYTMzMC03/NDNsLXRheGlpbmct/b3V0LXRvLXRoZS1y/dW53YXkuanBnP3M9/NjEyeDYxMiZ3PTAm/az0yMCZjPTdXYXRI/Uk94NnJnVHFxd01w/UlM2dUhUejRhZjdh/YS1VbGhNQTRNTlZX/RU09"
source: gettyimages.com
favicon_url: "https://imgs.search.brave.com/pi_-iHcSZ0f3mXMHIzy40iW0l1FZzm1LsS3d544QqYs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODc0ZTlhMjY4/MTM3N2MyZmQwMTNk/MmI0Y2UwMDUxMjM1/YjRlNDYyM2VkYmVl/NDk3MTUwOWI2Nzk0/MDZmMmZlYi93d3cu/Z2V0dHlpbWFnZXMu/Y29tLw"
hash: ca9668e715a8c45e
embed_ref: gettyimages.com-ZMz
app_id: images
skill_id: search`,
      parent_embed_id: "893f5c33-f98b-46e7-b81a-475a94827b35",
      embed_ids: null,
    },
    {
      embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      type: "app_skill_use",
      content: `app_id: web
skill_id: search
result_count: 6
embed_ids: 74a5a862-d322-4ac5-87fc-93f44068fdc5|c1981386-da72-4809-82a3-7411f0c9bd3c|4818c361-d1df-493b-8303-1ba34f64a716|3169e279-34a4-46d9-b0f2-9de349b1dea4|a1b1c8e9-279c-4b4b-8574-9723394b01f8|e9bbf72c-9b38-45b0-8206-a6a7f8fd3ee2
status: finished
query: Airbus Beluga and BelugaXL history and usage Europe airplane parts
provider: Brave`,
      parent_embed_id: null,
      embed_ids: ["74a5a862-d322-4ac5-87fc-93f44068fdc5", "c1981386-da72-4809-82a3-7411f0c9bd3c", "4818c361-d1df-493b-8303-1ba34f64a716", "3169e279-34a4-46d9-b0f2-9de349b1dea4", "a1b1c8e9-279c-4b4b-8574-9723394b01f8", "e9bbf72c-9b38-45b0-8206-a6a7f8fd3ee2"],
    },
    {
      embed_id: "c1981386-da72-4809-82a3-7411f0c9bd3c",
      type: "website",
      content: `type: search_result
title: Airbus Beluga - Wikipedia
url: "https://en.wikipedia.org/wiki/Airbus_Beluga"
description: "The BelugaXL is intended primarily for A350 work, designed to ship two A350 wings simultaneously. The first two aircraft were considered essential to facilitate mass production of the A350, while the following aircraft were to be progressively ..."
page_age: 2 weeks ago
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/AtMmU1TfU_Pryp_B0pd7gAZl3BMlzyf0NQqrk694g0w/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy9m/L2Y2L0hhbWJ1cmct/Rmlua2Vud2VyZGVy/X0FpcnBvcnRfQWly/YnVzX1RyYW5zcG9y/dF9JbnRlcm5hdGlv/bmFsX0FpcmJ1c19B/MzAwQjQtNjA4U1Rf/Ri1HU1REXyUyOERT/QzA5NjU2JTI5Lmpw/Zw"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/f/f6/Hamburg-Finkenwerder_Airport_Airbus_Transport_International_Airbus_A300B4-608ST_F-GSTD_%28DSC09656%29.jpg"
extra_snippets: "In addition to its primary task of conveying Airbus components, the Super Transporter fleet has occasionally been used for charter flights, carrying outsized cargoes for various customers and purposes, from whole helicopters to industrial equipment and humanitarian aid. On 25 January 2022, Airbus announced a service offering outsize cargo transportation using its Beluga fleet. During the 2010s, Airbus developed a slightly larger successor, the BelugaXL, based on the Airbus A330-200.|In November 2014, Airbus announced that it was proceeding with the development of a larger replacement based on the Airbus A330-200, planning to replace the BelugaST fleet entirely by 2025. The BelugaXL entered service in 2020. Airbus previously considered the A330-300 and A340-500, but each required too much of the limited 1,663 m (5,456 ft) runway at Hawarden Airport near Broughton in Wales.|In May 2015, Airbus confirmed that the new aircraft would have a 1 m (3 ft 3 in) wider cross-section than its predecessor and provide a 12% increase in payload. The BelugaXL is intended primarily for A350 work, designed to ship two A350 wings simultaneously. The first two aircraft were considered essential to facilitate mass production of the A350, while the following aircraft were to be progressively introduced as the A300-600 Beluga fleet was withdrawn.|The airline was established as an alternative use for the Beluga fleet, after it withdrawn from Airbus' internal logistics network after introduction of the BelugaXL.|The Beluga fleet is owned by Airbus Transport International (ATI), a wholly owned subsidiary of Airbus Group that was established specifically to operate the type; through this organisation, the fleet is made available for hire by third parties for charter flight."
hash: 493def7a9c1c0395
embed_ref: en.wikipedia.org-yXB
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "74a5a862-d322-4ac5-87fc-93f44068fdc5",
      type: "website",
      content: `type: search_result
title: Airbus BelugaXL - Wikipedia
url: "https://en.wikipedia.org/wiki/Airbus_BelugaXL"
description: "The time required for a BelugaST to move the parts of an A320 was three times as long as for the BelugaXL, and nine times longer for A350 parts. After an Airbus A350 production increase, Airbus aimed to deliver 880 aircraft in 2019, and raise ..."
page_age: 2 weeks ago
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/G2X0DlD_zmLypNjHrvrcqjx_UQKO63_CqByPeh4UZfY/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy8x/LzE5L0hhbWJ1cmct/Rmlua2Vud2VyZGVy/X0FpcnBvcnRfQWly/YnVzX1RyYW5zcG9y/dF9JbnRlcm5hdGlv/bmFsX0FpcmJ1c19B/MzMwLTc0M0xfQmVs/dWdhX1hMX0YtR1hM/SF8lMjhEU0MwOTM2/NSUyOS5qcGc"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/1/19/Hamburg-Finkenwerder_Airport_Airbus_Transport_International_Airbus_A330-743L_Beluga_XL_F-GXLH_%28DSC09365%29.jpg"
extra_snippets: "The time required for a BelugaST to move the parts of an A320 was three times as long as for the BelugaXL, and nine times longer for A350 parts. After an Airbus A350 production increase, Airbus aimed to deliver 880 aircraft in 2019, and raise A320neo output to 63 per month by 2021; the BelugaXL fleet was expanded with a sixth aircraft in June 2019.|The Airbus A330-743L BelugaXL is a large transport aircraft based on the Airbus A330-200F built by Airbus to supplement and potentially replace the original Airbus Beluga to transport very large aircraft components, such as wings. The aircraft made its first flight on 19 July 2018, and received its type certification on 13 November 2019.|The BelugaXL entered service with Airbus Transport on 9 January 2020. By 2013, the five original BelugaSTs could not cope with Airbus production growth, and the manufacturer evaluated the Antonov An-124 and An-225, Boeing C-17 and Dreamlifter, and A400M, before choosing to modify one of its own aircraft.|Airbus started operating the first BelugaXL on 9 January 2020, with all six freighters scheduled to be operating by the end of 2023, and the previous A300-600STs phased out as of 2021. With 30% more capacity than the original BelugaST, the BelugaXL can carry two A350 XWB wings instead of one.|Produced by Stelia Aerospace, its main freight door has 24 latches, and the nose includes the cockpit, while a four-seat courier section is supplied by Airbus. Its vertical stabiliser is 50% larger; it has auxiliary fins on the horizontal stabiliser, and two ventral fins beneath the empennage. The BelugaXL operates at Mach 0.69 up to 35,000 ft (11,000 m) over 2,300 nmi (4,300 km; 2,600 mi) instead of the original Beluga's 900 nmi (1,700 km; 1,000 mi)."
hash: dc42137a6c30fa05
embed_ref: en.wikipedia.org-49t
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "74a5a862-d322-4ac5-87fc-93f44068fdc5",
      type: "website",
      content: `type: search_result
title: Airbus BelugaXL - Wikipedia
url: "https://en.wikipedia.org/wiki/Airbus_BelugaXL"
description: "The time required for a BelugaST to move the parts of an A320 was three times as long as for the BelugaXL, and nine times longer for A350 parts. After an Airbus A350 production increase, Airbus aimed to deliver 880 aircraft in 2019, and raise ..."
page_age: 2 weeks ago
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/G2X0DlD_zmLypNjHrvrcqjx_UQKO63_CqByPeh4UZfY/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy8x/LzE5L0hhbWJ1cmct/Rmlua2Vud2VyZGVy/X0FpcnBvcnRfQWly/YnVzX1RyYW5zcG9y/dF9JbnRlcm5hdGlv/bmFsX0FpcmJ1c19B/MzMwLTc0M0xfQmVs/dWdhX1hMX0YtR1hM/SF8lMjhEU0MwOTM2/NSUyOS5qcGc"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/1/19/Hamburg-Finkenwerder_Airport_Airbus_Transport_International_Airbus_A330-743L_Beluga_XL_F-GXLH_%28DSC09365%29.jpg"
extra_snippets: "The time required for a BelugaST to move the parts of an A320 was three times as long as for the BelugaXL, and nine times longer for A350 parts. After an Airbus A350 production increase, Airbus aimed to deliver 880 aircraft in 2019, and raise A320neo output to 63 per month by 2021; the BelugaXL fleet was expanded with a sixth aircraft in June 2019.|The Airbus A330-743L BelugaXL is a large transport aircraft based on the Airbus A330-200F built by Airbus to supplement and potentially replace the original Airbus Beluga to transport very large aircraft components, such as wings. The aircraft made its first flight on 19 July 2018, and received its type certification on 13 November 2019.|The BelugaXL entered service with Airbus Transport on 9 January 2020. By 2013, the five original BelugaSTs could not cope with Airbus production growth, and the manufacturer evaluated the Antonov An-124 and An-225, Boeing C-17 and Dreamlifter, and A400M, before choosing to modify one of its own aircraft.|Airbus started operating the first BelugaXL on 9 January 2020, with all six freighters scheduled to be operating by the end of 2023, and the previous A300-600STs phased out as of 2021. With 30% more capacity than the original BelugaST, the BelugaXL can carry two A350 XWB wings instead of one.|Produced by Stelia Aerospace, its main freight door has 24 latches, and the nose includes the cockpit, while a four-seat courier section is supplied by Airbus. Its vertical stabiliser is 50% larger; it has auxiliary fins on the horizontal stabiliser, and two ventral fins beneath the empennage. The BelugaXL operates at Mach 0.69 up to 35,000 ft (11,000 m) over 2,300 nmi (4,300 km; 2,600 mi) instead of the original Beluga's 900 nmi (1,700 km; 1,000 mi)."
hash: dc42137a6c30fa05
embed_ref: en.wikipedia.org-49t
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "a1b1c8e9-279c-4b4b-8574-9723394b01f8",
      type: "website",
      content: `type: search_result
title: "Airbus Beluga XL · History, Technical Data & Photos · AeroCorner"
url: "https://aerocorner.com/aircraft/airbus-beluga-xl/"
description: "The Airbus BelugaXL was developed to move large aircraft components between Airbus production facilities across Europe. Based on the Airbus A330 platform, it dramatically increased cargo capacity over its predecessor and became a critical part ..."
page_age: "February 23, 2026"
profile_name: AeroCorner
meta_url_favicon: "https://imgs.search.brave.com/gGr_wPRDTCdb6mIklVN_nrIek6NqnyMmCw7uW9YjIyM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTNlYTZjOTkz/YTM3YTVlMzlhYzMy/OGIyYmMzYjJkN2Q1/ODhhOTNlOGJiZDll/Zjg2MWVhYjQ5MTA4/YWZhYzM4Mi9hZXJv/Y29ybmVyLmNvbS8"
thumbnail_src: "https://imgs.search.brave.com/JNVC0P6rAGp5CgYZsbUhhEmlhnl1qhYJ-W1ZiLf7ywI/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9hZXJv/Y29ybmVyLmNvbS93/cC1jb250ZW50L3Vw/bG9hZHMvMjAyMS8w/Ni9CZWx1Z2EtWEwt/b2YtQWlyYnVzLVRy/YW5zcG9ydC1JbnRl/cm5hdGlvbmFsLS0x/NTM2eDY2Mi5qcGVn"
thumbnail_original: "https://aerocorner.com/wp-content/uploads/2021/06/Beluga-XL-of-Airbus-Transport-International--1536x662.jpeg"
extra_snippets: "The Airbus BelugaXL was developed to move large aircraft components between Airbus production facilities across Europe. Based on the Airbus A330 platform, it dramatically increased cargo capacity over its predecessor and became a critical part of Airbus’s internal logistics network. ... We have laid out a basic primer on the various types of airplane in use today.|Enter Airplane Repo, a Discovery Channel reality series that claimed to showcase repo agents taking […] The Airbus BelugaXL is a large cargo aircraft designed specifically to transport oversized aircraft components such as wings and fuselage sections between Airbus manufacturing sites. Launched in 2014 as a replacement for the earlier A300-600ST Beluga, the BelugaXL is based on the Airbus A330-200 platform and incorporates a heavily modified upper fuselage to accommodate its massive cargo hold.|The BelugaXL is not a commercial freight aircraft but a strategic industrial tool that supports Airbus’s distributed manufacturing model. By increasing transport efficiency between facilities in France, Germany, Spain, and the United Kingdom, the aircraft plays a vital role in maintaining production rates for Airbus widebody programs. Airbus had made five of the original Beluga aircraft by 2013.|Airbus replaced its five-aircraft A300-600ST fleet with six BelugaXL aircraft, derived from the company’s versatile A330 wide-body product line. Launched in November 2014, it received European Union Aviation Safety Agency (EASA) certification on November 13, 2019, following tests over 200 flights and more than 700 hours."
hash: 7a9fc3643776b7b3
embed_ref: aerocorner.com-Bci
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "3169e279-34a4-46d9-b0f2-9de349b1dea4",
      type: "website",
      content: `type: search_result
title: Why Has Airbus Built The BelugaXL Aircraft Type?
url: "https://simpleflying.com/airbus-beluga-xl-why/"
description: "Five Beluga aircraft were delivered between 1995 and 1999. Four are still active today, while the first to be built was retired in 2021. The BelugaXL program was launched in 2014, and the aircraft performed its maiden flight in 2018."
page_age: "October 13, 2023"
profile_name: Simple Flying
meta_url_favicon: "https://imgs.search.brave.com/VMQLlOIvBT3gsq5BXX5pTGGXEXcs37fApdqzYAnDJCU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzljZjhiMmE3/ZDkwMWJiMmEwNjY2/ZTVlYWM0NTk2Mjk2/MzUwODcwMDNiZDE3/MTdmODg5MDBmY2Iw/MzM2NGIwZC9zaW1w/bGVmbHlpbmcuY29t/Lw"
thumbnail_src: "https://imgs.search.brave.com/LMx8p27y87ygZNQsbq1JxH8WSg3aXN-MTyQJE-4_CAI/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zdGF0/aWMwLnNpbXBsZWZs/eWluZ2ltYWdlcy5j/b20vd29yZHByZXNz/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDIz/LzEwL2JlbHVnYXhs/LW92ZXItdGhlLWVs/YmUtMS5qcGc_dz0x/NjAwJmg9OTAwJmZp/dD1jcm9w"
thumbnail_original: "https://static0.simpleflyingimages.com/wordpress/wp-content/uploads/2023/10/belugaxl-over-the-elbe-1.jpg?w=1600&h=900&fit=crop"
extra_snippets: "It is a distinctive cargo aircraft, modified from the A330, with an equally characteristic smiling whale appearance. Airbus operates the BelugaST and the larger BelugaXL to transport parts of its aircraft between construction and assembly sites, as this article explores.|While their primary role has been transporting Airbus aircraft components between European sites, they have also seen plenty of charter use, including carrying machinery, helicopters, and satellite parts. Want answers to more key questions in aviation? Check out the rest of our guides here. Five Beluga aircraft were delivered between 1995 and 1999. Four are still active today, while the first to be built was retired in 2021. The BelugaXL program was launched in 2014, and the aircraft performed its maiden flight in 2018.|The BelugaXL, a larger and more advanced version of the Beluga, transports Airbus aircraft parts between construction and assembly sites.|As more aircraft would help Airbus meet growing transportation needs, the newer cargo plane came with critically higher capacity. The original Beluga can carry 103,617 lb (47,000 kg) in a freight compartment with a volume of 53,000 cu ft (1,500 cubic meters). The BelugaXL increases this to 111,333 lb (50,500 kg) with a volume of 78,000 cu ft."
hash: b5965b51ab014a7f
embed_ref: simpleflying.com-KkO
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "e9bbf72c-9b38-45b0-8206-a6a7f8fd3ee2",
      type: "website",
      content: `type: search_result
title: An iconic Airbus BelugaST readies for new mission in the UK
url: "https://www.airbus.com/en/newsroom/press-releases/2026-01-an-iconic-airbus-belugast-readies-for-new-mission-in-the-uk"
description: "... The BelugaST fleet entered service in 1995 to replace the \\"Super Guppy.\\" It revolutionised how Airbus’ aircraft components were moved across Europe, allowing Airbus to scale production to record levels."
page_age: "January 29, 2026"
profile_name: Airbus
meta_url_favicon: "https://imgs.search.brave.com/tJq33aA1npzJEHeFnfm8YSqRIh171GRlmnDVGahHZk8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDA5YTJiNTgy/YmViZWJmYTIyZTkz/MDI2MjE2MDIzMjli/ZjFlNDZhMjhhNmEw/MDIxYzdjYWI0OTAx/YzExY2M3Ny93d3cu/YWlyYnVzLmNvbS8"
thumbnail_src: "https://imgs.search.brave.com/u3syQQjHggy1cnT2uS0dgxU1ZHOz0O6eSbj44ub2BQo/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9tZWRp/YWFzc2V0cy5haXJi/dXMuY29tL3BtXzM4/Xzc4Ml83ODIyOTgt/YXBnMWNvd29oaS1w/cmV2aWV3LmpwZw"
thumbnail_original: "https://mediaassets.airbus.com/pm_38_782_782298-apg1cowohi-preview.jpg"
extra_snippets: "Beluga lovers everywhere will still be able to see the replacement of the BelugaST, the even larger BelugaXL in the skies, transporting Airbus components to 11 sites around Europe. Airbus announced the retirement of the BelugaST fleet earlier in 2025.|From mid-2027, the larger BelugaXL fleet will be the sole transporter of components for Airbus. ... The BelugaST fleet entered service in 1995 to replace the \\"Super Guppy.\\" It revolutionised how Airbus’ aircraft components were moved across Europe, allowing Airbus to scale production to record levels.|The BelugaST fleet, first launched in 1994, has predominantly been used to transport wings made in the UK to other Airbus facilities around Europe. Gareth Davies, Head of Airbus Broughton, said, \\"It’s a proud and incredibly exciting moment for Broughton. This particular Beluga first took flight 25 years ago, and since then has played a crucial part in transporting our wings from Broughton to Airbus’ mainland European sites.|Broughton, UK, 29 January 2026 - One of Airbus’ BelugaST aircraft, formally among the largest in the world, will be rehomed in the UK, with plans to turn it into a Science, Technology, Engineering and Maths (STEM) support facility at Airbus Broughton."
hash: 848830c84d112d30
embed_ref: airbus.com-lTo
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "3169e279-34a4-46d9-b0f2-9de349b1dea4",
      type: "website",
      content: `type: search_result
title: Why Has Airbus Built The BelugaXL Aircraft Type?
url: "https://simpleflying.com/airbus-beluga-xl-why/"
description: "Five Beluga aircraft were delivered between 1995 and 1999. Four are still active today, while the first to be built was retired in 2021. The BelugaXL program was launched in 2014, and the aircraft performed its maiden flight in 2018."
page_age: "October 13, 2023"
profile_name: Simple Flying
meta_url_favicon: "https://imgs.search.brave.com/VMQLlOIvBT3gsq5BXX5pTGGXEXcs37fApdqzYAnDJCU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzljZjhiMmE3/ZDkwMWJiMmEwNjY2/ZTVlYWM0NTk2Mjk2/MzUwODcwMDNiZDE3/MTdmODg5MDBmY2Iw/MzM2NGIwZC9zaW1w/bGVmbHlpbmcuY29t/Lw"
thumbnail_src: "https://imgs.search.brave.com/LMx8p27y87ygZNQsbq1JxH8WSg3aXN-MTyQJE-4_CAI/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zdGF0/aWMwLnNpbXBsZWZs/eWluZ2ltYWdlcy5j/b20vd29yZHByZXNz/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDIz/LzEwL2JlbHVnYXhs/LW92ZXItdGhlLWVs/YmUtMS5qcGc_dz0x/NjAwJmg9OTAwJmZp/dD1jcm9w"
thumbnail_original: "https://static0.simpleflyingimages.com/wordpress/wp-content/uploads/2023/10/belugaxl-over-the-elbe-1.jpg?w=1600&h=900&fit=crop"
extra_snippets: "It is a distinctive cargo aircraft, modified from the A330, with an equally characteristic smiling whale appearance. Airbus operates the BelugaST and the larger BelugaXL to transport parts of its aircraft between construction and assembly sites, as this article explores.|While their primary role has been transporting Airbus aircraft components between European sites, they have also seen plenty of charter use, including carrying machinery, helicopters, and satellite parts. Want answers to more key questions in aviation? Check out the rest of our guides here. Five Beluga aircraft were delivered between 1995 and 1999. Four are still active today, while the first to be built was retired in 2021. The BelugaXL program was launched in 2014, and the aircraft performed its maiden flight in 2018.|The BelugaXL, a larger and more advanced version of the Beluga, transports Airbus aircraft parts between construction and assembly sites.|As more aircraft would help Airbus meet growing transportation needs, the newer cargo plane came with critically higher capacity. The original Beluga can carry 103,617 lb (47,000 kg) in a freight compartment with a volume of 53,000 cu ft (1,500 cubic meters). The BelugaXL increases this to 111,333 lb (50,500 kg) with a volume of 78,000 cu ft."
hash: b5965b51ab014a7f
embed_ref: simpleflying.com-KkO
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "4818c361-d1df-493b-8303-1ba34f64a716",
      type: "website",
      content: `type: search_result
title: The iconic Airbus Beluga Super Transporter | Airbus
url: "https://www.airbus.com/en/products-services/commercial-aircraft/freighter/beluga"
description: "The BelugaXL performed its maiden flight in 2018, featuring the iconic 'smiley' livery that was chosen by Airbus employees in a vote by almost 21,000 participants. The six-aircraft BelugaXL fleet is operated by Airbus Transport International (ATI), an Airbus subsidiary that has been the company's ..."
page_age: "March 12, 2025"
profile_name: Airbus
meta_url_favicon: "https://imgs.search.brave.com/tJq33aA1npzJEHeFnfm8YSqRIh171GRlmnDVGahHZk8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDA5YTJiNTgy/YmViZWJmYTIyZTkz/MDI2MjE2MDIzMjli/ZjFlNDZhMjhhNmEw/MDIxYzdjYWI0OTAx/YzExY2M3Ny93d3cu/YWlyYnVzLmNvbS8"
thumbnail: null
extra_snippets: "The BelugaXL performed its maiden flight in 2018, featuring the iconic 'smiley' livery that was chosen by Airbus employees in a vote by almost 21,000 participants. The six-aircraft BelugaXL fleet is operated by Airbus Transport International (ATI), an Airbus subsidiary that has been the company's internal airline since 1996. ... For 30 years, the iconic BelugaST (Super Transporter) also known as the A300-600ST, played a central role in connecting our European production and assembly facilities.|The Beluga is designed to carry oversized cargo, especially the large parts required for assembling commercial aircraft. Essentially, anything that is too large for standard freight carriers but critical to Airbus’s production process is a potential load for the Beluga. Examples include: Aircraft wings (such as the wings for the Airbus A350 or A320) ... Large and complex components used in aircraft assembly that exceed the size limitations of regular cargo planes · The BelugaST and BelugaXL represent two generations of the Airbus Super Transporter.|The newer BelugaXL is based on the A330 platform, featuring a wider fuselage and more capacity than the BelugaST. It can carry up to 51 tonnes of cargo and handle cargo up to 63 metres in length, making it much more efficient for transporting larger and heavier parts in the Airbus production chain.|The Beluga aircraft enable Airbus to efficiently move parts across these various sites, making sure that the assembly of aircraft remains on schedule. As we transition to solely using the BelugaXL fleet, our BelugaST's will be repositioned to a new mission."
hash: b26e2a1f56f544a0
embed_ref: airbus.com-ilV
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "4818c361-d1df-493b-8303-1ba34f64a716",
      type: "website",
      content: `type: search_result
title: The iconic Airbus Beluga Super Transporter | Airbus
url: "https://www.airbus.com/en/products-services/commercial-aircraft/freighter/beluga"
description: "The BelugaXL performed its maiden flight in 2018, featuring the iconic 'smiley' livery that was chosen by Airbus employees in a vote by almost 21,000 participants. The six-aircraft BelugaXL fleet is operated by Airbus Transport International (ATI), an Airbus subsidiary that has been the company's ..."
page_age: "March 12, 2025"
profile_name: Airbus
meta_url_favicon: "https://imgs.search.brave.com/tJq33aA1npzJEHeFnfm8YSqRIh171GRlmnDVGahHZk8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDA5YTJiNTgy/YmViZWJmYTIyZTkz/MDI2MjE2MDIzMjli/ZjFlNDZhMjhhNmEw/MDIxYzdjYWI0OTAx/YzExY2M3Ny93d3cu/YWlyYnVzLmNvbS8"
thumbnail: null
extra_snippets: "The BelugaXL performed its maiden flight in 2018, featuring the iconic 'smiley' livery that was chosen by Airbus employees in a vote by almost 21,000 participants. The six-aircraft BelugaXL fleet is operated by Airbus Transport International (ATI), an Airbus subsidiary that has been the company's internal airline since 1996. ... For 30 years, the iconic BelugaST (Super Transporter) also known as the A300-600ST, played a central role in connecting our European production and assembly facilities.|The Beluga is designed to carry oversized cargo, especially the large parts required for assembling commercial aircraft. Essentially, anything that is too large for standard freight carriers but critical to Airbus’s production process is a potential load for the Beluga. Examples include: Aircraft wings (such as the wings for the Airbus A350 or A320) ... Large and complex components used in aircraft assembly that exceed the size limitations of regular cargo planes · The BelugaST and BelugaXL represent two generations of the Airbus Super Transporter.|The newer BelugaXL is based on the A330 platform, featuring a wider fuselage and more capacity than the BelugaST. It can carry up to 51 tonnes of cargo and handle cargo up to 63 metres in length, making it much more efficient for transporting larger and heavier parts in the Airbus production chain.|The Beluga aircraft enable Airbus to efficiently move parts across these various sites, making sure that the assembly of aircraft remains on schedule. As we transition to solely using the BelugaXL fleet, our BelugaST's will be repositioned to a new mission."
hash: b26e2a1f56f544a0
embed_ref: airbus.com-ilV
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "c1981386-da72-4809-82a3-7411f0c9bd3c",
      type: "website",
      content: `type: search_result
title: Airbus Beluga - Wikipedia
url: "https://en.wikipedia.org/wiki/Airbus_Beluga"
description: "The BelugaXL is intended primarily for A350 work, designed to ship two A350 wings simultaneously. The first two aircraft were considered essential to facilitate mass production of the A350, while the following aircraft were to be progressively ..."
page_age: 2 weeks ago
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/AtMmU1TfU_Pryp_B0pd7gAZl3BMlzyf0NQqrk694g0w/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy9m/L2Y2L0hhbWJ1cmct/Rmlua2Vud2VyZGVy/X0FpcnBvcnRfQWly/YnVzX1RyYW5zcG9y/dF9JbnRlcm5hdGlv/bmFsX0FpcmJ1c19B/MzAwQjQtNjA4U1Rf/Ri1HU1REXyUyOERT/QzA5NjU2JTI5Lmpw/Zw"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/f/f6/Hamburg-Finkenwerder_Airport_Airbus_Transport_International_Airbus_A300B4-608ST_F-GSTD_%28DSC09656%29.jpg"
extra_snippets: "In addition to its primary task of conveying Airbus components, the Super Transporter fleet has occasionally been used for charter flights, carrying outsized cargoes for various customers and purposes, from whole helicopters to industrial equipment and humanitarian aid. On 25 January 2022, Airbus announced a service offering outsize cargo transportation using its Beluga fleet. During the 2010s, Airbus developed a slightly larger successor, the BelugaXL, based on the Airbus A330-200.|In November 2014, Airbus announced that it was proceeding with the development of a larger replacement based on the Airbus A330-200, planning to replace the BelugaST fleet entirely by 2025. The BelugaXL entered service in 2020. Airbus previously considered the A330-300 and A340-500, but each required too much of the limited 1,663 m (5,456 ft) runway at Hawarden Airport near Broughton in Wales.|In May 2015, Airbus confirmed that the new aircraft would have a 1 m (3 ft 3 in) wider cross-section than its predecessor and provide a 12% increase in payload. The BelugaXL is intended primarily for A350 work, designed to ship two A350 wings simultaneously. The first two aircraft were considered essential to facilitate mass production of the A350, while the following aircraft were to be progressively introduced as the A300-600 Beluga fleet was withdrawn.|The airline was established as an alternative use for the Beluga fleet, after it withdrawn from Airbus' internal logistics network after introduction of the BelugaXL.|The Beluga fleet is owned by Airbus Transport International (ATI), a wholly owned subsidiary of Airbus Group that was established specifically to operate the type; through this organisation, the fleet is made available for hire by third parties for charter flight."
hash: 493def7a9c1c0395
embed_ref: en.wikipedia.org-yXB
app_id: web
skill_id: search`,
      parent_embed_id: "040ef265-5dc8-4512-b443-b52bc86f7a6b",
      embed_ids: null,
    },
    {
      embed_id: "74dcc340-4db8-4f52-8761-ce46b46ad709",
      type: "image_result",
      content: `type: image_result
title: Stratolaunch ROC
source_page_url: "https://www.jetsprops.com/transport/stratolaunch-roc-the-worlds-largest-aircraft.html"
image_url: "https://www.jetsprops.com/wp-content/uploads/2023/06/drone-2.jpg"
thumbnail_url: "https://imgs.search.brave.com/iGQMj6_QqTpqElp_ECF7y5Qc3JBulHl0xQgIRVdWEiw/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/amV0c3Byb3BzLmNv/bS93cC1jb250ZW50/L3VwbG9hZHMvMjAy/My8wNi9kcm9uZS0y/LmpwZw"
source: jetsprops.com
favicon_url: "https://imgs.search.brave.com/evSyBuhkwi6f6gd3qdEFxK6mgSobrFy0h8HbF7dnpHg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMWQ2NDIwZjcz/YTQ5YTFhNjdlNmI3/OGEyOTY1NmUyOGJk/YWVlODQwODRmYzZi/MTgzYzVlNDEyYzBi/NDg1MzlkMS93d3cu/amV0c3Byb3BzLmNv/bS8"
hash: 2adc88eb4c8ad092
embed_ref: jetsprops.com-uun
app_id: images
skill_id: search`,
      parent_embed_id: "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e",
      embed_ids: null,
    },
    {
      embed_id: "6fa003c9-892a-4608-8fb3-d8693eaa856e",
      type: "image_result",
      content: `type: image_result
title: NASA’s Super Guppy Is Transporting Rocket Parts for the 2025 Moon Landings
source_page_url: "https://interestingengineering.com/transportation/nasa-super-guppy-transporting-rocket-parts-for-artemis"
image_url: "https://interestingengineering.com/_next/image?url=https://images.interestingengineering.com/img/iea/9lwjZglVwE/super-guppy.jpg&w=3840&q=75"
thumbnail_url: "https://imgs.search.brave.com/3uVD9v47DExFQkypUS4chG37Jjb2JqTHZ6qAgOtqXCc/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pbnRl/cmVzdGluZ2VuZ2lu/ZWVyaW5nLmNvbS9f/bmV4dC9pbWFnZT91/cmw9aHR0cHM6Ly9p/bWFnZXMuaW50ZXJl/c3RpbmdlbmdpbmVl/cmluZy5jb20vaW1n/L2llYS85bHdqWmds/VndFL3N1cGVyLWd1/cHB5LmpwZyZ3PTM4/NDAmcT03NQ"
source: interestingengineering.com
favicon_url: "https://imgs.search.brave.com/RZEGJithNwyfjOMM8FdFlglO2qxgdvpd-PIAgRnff14/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNThhNWFmMjZj/YzYyMmI3ZWY2NjMx/MjgyMmQzNDY1ODhj/ZjI4OTIwMGIyYWM2/MTIxNTNmNTlmNzNm/NjRkOGNmMS9pbnRl/cmVzdGluZ2VuZ2lu/ZWVyaW5nLmNvbS8"
hash: 14882dabfa29d15b
embed_ref: interestingengineering.com-fne
app_id: images
skill_id: search`,
      parent_embed_id: "5e183917-41a3-45f4-a0e7-e01e346b1e58",
      embed_ids: null,
    },
    {
      embed_id: "bfb8d5e2-2808-4b06-835d-2556d8e3ccb4",
      type: "image_result",
      content: `type: image_result
title: "The Aero Spacelines 377-SG \\"Super Guppy\\", a super-transport aircraft used by NASA until 1991."
source_page_url: "https://pimaair.org/museum-aircraft/aero-spacelines-377g-super-guppy/"
image_url: "https://pimaair.org/wp-content/uploads/2019/11/Aerospacelines-Guppy.jpg"
thumbnail_url: "https://imgs.search.brave.com/UHTAJ_zG2y4cOKWmnAObYAc-pseAyb1UoLpW_PgX8x0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9waW1h/YWlyLm9yZy93cC1j/b250ZW50L3VwbG9h/ZHMvMjAxOS8xMS9B/ZXJvc3BhY2VsaW5l/cy1HdXBweS5qcGc"
source: pimaair.org
favicon_url: "https://imgs.search.brave.com/kocHfHVYrqiFVQ2U_DBCb1mbnHqWprRZw9I6oJLwRqw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjNlMzQ3ZGNj/ZTQ1NzljMzVhNWMx/M2JjOGYxOGZkZDBi/ZWQ5NmYyMzQ1ZjIy/MWU5MGEzMGVhZDk5/NjcyZDc1Mi9waW1h/YWlyLm9yZy8"
hash: 1e783c4039201f8d
embed_ref: pimaair.org-CDS
app_id: images
skill_id: search`,
      parent_embed_id: "5e183917-41a3-45f4-a0e7-e01e346b1e58",
      embed_ids: null,
    },
    {
      embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 299f62b8-51be-4103-94c1-3fcacf754735|8bf3382a-8b7d-475a-9907-9bf99d16316e|f5339e36-2e68-4bc1-a7f4-bebfd8597837|3a173c45-654c-4bae-88f1-b84ed4e9b635|b5d2d78b-cb58-4a4f-a5aa-237d04a2ad52|a95a3602-3009-494e-97d7-aa471ceb1297
status: finished
query: Antonov An-225 Mriya rocket transport
id: 1
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["299f62b8-51be-4103-94c1-3fcacf754735", "8bf3382a-8b7d-475a-9907-9bf99d16316e", "f5339e36-2e68-4bc1-a7f4-bebfd8597837", "3a173c45-654c-4bae-88f1-b84ed4e9b635", "b5d2d78b-cb58-4a4f-a5aa-237d04a2ad52", "a95a3602-3009-494e-97d7-aa471ceb1297"],
    },
    {
      embed_id: "25d433ee-422c-4b86-a34d-89f4392ac25c",
      type: "image_result",
      content: `type: image_result
title: "r/interestingasfuck - NASA has a plane called Super Guppy that's designed to transport rockets, large equipment and even other planes"
source_page_url: "https://www.reddit.com/r/interestingasfuck/comments/odlpql/nasa_has_a_plane_called_super_guppy_thats/"
image_url: "https://external-preview.redd.it/nasa-has-a-plane-called-super-guppy-thats-designed-to-v0-s0-Fure1-WND-BDHws5tg598M-CQFQVGLgTwvtT27us.jpg?width=640&crop=smart&auto=webp&s=1337e481abe2d8ccc2501809f2927e148712dfab"
thumbnail_url: "https://imgs.search.brave.com/U8E4JWDmURV53Zm9xA-GldZV-laaMg5Qg7HMsrToAo0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9leHRl/cm5hbC1wcmV2aWV3/LnJlZGQuaXQvbmFz/YS1oYXMtYS1wbGFu/ZS1jYWxsZWQtc3Vw/ZXItZ3VwcHktdGhh/dHMtZGVzaWduZWQt/dG8tdjAtczAtRnVy/ZTEtV05ELUJESHdz/NXRnNTk4TS1DUUZR/VkdMZ1R3dnRUMjd1/cy5qcGc_d2lkdGg9/NjQwJmNyb3A9c21h/cnQmYXV0bz13ZWJw/JnM9MTMzN2U0ODFh/YmUyZDhjY2MyNTAx/ODA5ZjI5MjdlMTQ4/NzEyZGZhYg"
source: reddit.com
favicon_url: "https://imgs.search.brave.com/U-eHNCapRHVNWWCVPPMTIvOofZULh0_A_FQKe8xTE4I/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvN2ZiNTU0M2Nj/MTFhZjRiYWViZDlk/MjJiMjBjMzFjMDRk/Y2IzYWI0MGI0MjVk/OGY5NzQzOGQ5NzQ5/NWJhMWI0NC93d3cu/cmVkZGl0LmNvbS8"
hash: 01e2e73d68a8d48f
embed_ref: reddit.com-eHx
app_id: images
skill_id: search`,
      parent_embed_id: "5e183917-41a3-45f4-a0e7-e01e346b1e58",
      embed_ids: null,
    },
    {
      embed_id: "46273a0f-95bf-4a63-8629-5408559ef119",
      type: "image_result",
      content: `type: image_result
title: USA - Transportation - 747-400 Airplane
source_page_url: "https://www.cnet.com/pictures/meet-the-stratolaunch-the-worlds-largest-airplane/"
image_url: "https://www.cnet.com/a/img/resize/701bab3a09cc132f4be0f0db8d1da38243d0986f/hub/2017/06/05/33558034-ca2d-41cd-889f-65697af1ef22/cnet-stratolaunch-21.jpg?auto=webp&width=1200"
thumbnail_url: "https://imgs.search.brave.com/U2zOBZx8j129RfjjuAG51EDxWjTtO0aZXrTfU2_LHXw/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/Y25ldC5jb20vYS9p/bWcvcmVzaXplLzcw/MWJhYjNhMDljYzEz/MmY0YmUwZjBkYjhk/MWRhMzgyNDNkMDk4/NmYvaHViLzIwMTcv/MDYvMDUvMzM1NTgw/MzQtY2EyZC00MWNk/LTg4OWYtNjU2OTdh/ZjFlZjIyL2NuZXQt/c3RyYXRvbGF1bmNo/LTIxLmpwZz9hdXRv/PXdlYnAmd2lkdGg9/MTIwMA"
source: cnet.com
favicon_url: "https://imgs.search.brave.com/mWlG-6ikaw-opvXdUS2O5Ia2lYTwH6MNnfeV64-Abho/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYWVkNmIyYmM4/MmJlODJlZDJjYTBh/MWE2MmMwMmVkOTdk/OThhMmU4ZjE0MTY4/MzAxYTcyNjI5OGI5/OGJhN2NmYS93d3cu/Y25ldC5jb20v"
hash: 1e862394db3ea9dc
embed_ref: cnet.com-sk5
app_id: images
skill_id: search`,
      parent_embed_id: "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e",
      embed_ids: null,
    },
    {
      embed_id: "80104e79-23b5-4065-9f1a-5d0453bb02dd",
      type: "image_result",
      content: `type: image_result
title: "Fit check of the Orion Crew and Service Module Horizontal Transporter with NASA's Super Guppy aircraft began March 12, 2019."
source_page_url: "https://www.nasa.gov/missions/artemis/orion/orion-transport-fixture-fit-checked-in-nasas-super-guppy-aircraft/"
image_url: "https://www.nasa.gov/wp-content/uploads/2019/04/guppy_fit_check_side2.jpg?w=2048"
thumbnail_url: "https://imgs.search.brave.com/ZUPTamwTvWkD620lx9P-Or6FEUpOvIT5C4IPlNXY8cE/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMTkvMDQv/Z3VwcHlfZml0X2No/ZWNrX3NpZGUyLmpw/Zz93PTIwNDg"
source: nasa.gov
favicon_url: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
hash: 1dcc8da2b3faafc8
embed_ref: nasa.gov-EW9
app_id: images
skill_id: search`,
      parent_embed_id: "5e183917-41a3-45f4-a0e7-e01e346b1e58",
      embed_ids: null,
    },
    {
      embed_id: "49c47c14-3977-4d22-84d0-fc2ce73669f6",
      type: "image_result",
      content: `type: image_result
title: The Orion horizontal transporter is fit-checked with the NASA Super Guppy aircraft at Kennedy Space Center in Florida.
source_page_url: "https://www.nasa.gov/missions/artemis/orion/orion-transport-fixture-fit-checked-in-nasas-super-guppy-aircraft/"
image_url: "https://www.nasa.gov/wp-content/uploads/2019/04/guppy_fit_check_side.jpg?w=2048"
thumbnail_url: "https://imgs.search.brave.com/fqd5YqN4iksc84w9G-On3vOPBIBjCgjXysqfI8lI7TA/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMTkvMDQv/Z3VwcHlfZml0X2No/ZWNrX3NpZGUuanBn/P3c9MjA0OA"
source: nasa.gov
favicon_url: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
hash: febfbae5f5c49577
embed_ref: nasa.gov-IKy
app_id: images
skill_id: search`,
      parent_embed_id: "5e183917-41a3-45f4-a0e7-e01e346b1e58",
      embed_ids: null,
    },
    {
      embed_id: "5d9b87b4-4f9a-44ee-b8c0-ec0c44010737",
      type: "image_result",
      content: `type: image_result
title: NASA's Super Guppy transport plane waits to ferry the Orion capsule from Florida to Plum Brook Station in Ohio for testing.
source_page_url: "https://www.space.com/nasa-orion-super-guppy-ride-photos-video.html"
image_url: "https://cdn.mos.cms.futurecdn.net/R7gVLGNvdqmWjQENXBJTPb.jpg"
thumbnail_url: "https://imgs.search.brave.com/dQcHEa3p-BjwfWaeHomn0T0RX5xg2S5ewkASqVMBXD0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L1I3/Z1ZMR052ZHFtV2pR/RU5YQkpUUGIuanBn"
source: space.com
favicon_url: "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
hash: 35b5209fb2261909
embed_ref: space.com-NMI
app_id: images
skill_id: search`,
      parent_embed_id: "5e183917-41a3-45f4-a0e7-e01e346b1e58",
      embed_ids: null,
    },
    {
      embed_id: "5e183917-41a3-45f4-a0e7-e01e346b1e58",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 6fa003c9-892a-4608-8fb3-d8693eaa856e|25d433ee-422c-4b86-a34d-89f4392ac25c|49c47c14-3977-4d22-84d0-fc2ce73669f6|bfb8d5e2-2808-4b06-835d-2556d8e3ccb4|80104e79-23b5-4065-9f1a-5d0453bb02dd|5d9b87b4-4f9a-44ee-b8c0-ec0c44010737
status: finished
query: NASA Super Guppy rocket transport
id: 2
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["6fa003c9-892a-4608-8fb3-d8693eaa856e", "25d433ee-422c-4b86-a34d-89f4392ac25c", "49c47c14-3977-4d22-84d0-fc2ce73669f6", "bfb8d5e2-2808-4b06-835d-2556d8e3ccb4", "80104e79-23b5-4065-9f1a-5d0453bb02dd", "5d9b87b4-4f9a-44ee-b8c0-ec0c44010737"],
    },
    {
      embed_id: "c3e95fb4-503f-4ca2-8a33-b1c818fd147c",
      type: "image_result",
      content: `type: image_result
title: cnet-stratolaunch-2
source_page_url: "https://www.cnet.com/pictures/meet-the-stratolaunch-the-worlds-largest-airplane/"
image_url: "https://www.cnet.com/a/img/resize/2adb13712268e67c5dfcbdd68a86fcd86942ab84/hub/2020/02/04/079f3635-78b9-4d36-843e-1ccc176dcf94/cnet-stratolaunch-new-cover.jpg?auto=webp&width=1200"
thumbnail_url: "https://imgs.search.brave.com/kzepKwX0ju7aCbHgrvY5ONyOPVlLS30LAgHTlfUUYOs/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/Y25ldC5jb20vYS9p/bWcvcmVzaXplLzJh/ZGIxMzcxMjI2OGU2/N2M1ZGZjYmRkNjhh/ODZmY2Q4Njk0MmFi/ODQvaHViLzIwMjAv/MDIvMDQvMDc5ZjM2/MzUtNzhiOS00ZDM2/LTg0M2UtMWNjYzE3/NmRjZjk0L2NuZXQt/c3RyYXRvbGF1bmNo/LW5ldy1jb3Zlci5q/cGc_YXV0bz13ZWJw/JndpZHRoPTEyMDA"
source: cnet.com
favicon_url: "https://imgs.search.brave.com/mWlG-6ikaw-opvXdUS2O5Ia2lYTwH6MNnfeV64-Abho/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYWVkNmIyYmM4/MmJlODJlZDJjYTBh/MWE2MmMwMmVkOTdk/OThhMmU4ZjE0MTY4/MzAxYTcyNjI5OGI5/OGJhN2NmYS93d3cu/Y25ldC5jb20v"
hash: bdb6c12d1c76d6ec
embed_ref: cnet.com-ML7
app_id: images
skill_id: search`,
      parent_embed_id: "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e",
      embed_ids: null,
    },
    {
      embed_id: "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 46273a0f-95bf-4a63-8629-5408559ef119|74dcc340-4db8-4f52-8761-ce46b46ad709|83b4f9e0-8739-4a8f-add6-e18f68ef21b9|f506ec66-a530-4c1c-b8b2-f02eebd61745|169624f7-f9fa-4a76-8633-1308a5291027|c3e95fb4-503f-4ca2-8a33-b1c818fd147c
status: finished
query: Stratolaunch Roc rocket transport
id: 3
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["46273a0f-95bf-4a63-8629-5408559ef119", "74dcc340-4db8-4f52-8761-ce46b46ad709", "83b4f9e0-8739-4a8f-add6-e18f68ef21b9", "f506ec66-a530-4c1c-b8b2-f02eebd61745", "169624f7-f9fa-4a76-8633-1308a5291027", "c3e95fb4-503f-4ca2-8a33-b1c818fd147c"],
    },
    {
      embed_id: "f506ec66-a530-4c1c-b8b2-f02eebd61745",
      type: "image_result",
      content: `type: image_result
title: Stratolaunch ROC
source_page_url: "https://www.jetsprops.com/transport/stratolaunch-roc-the-worlds-largest-aircraft.html"
image_url: "https://www.jetsprops.com/wp-content/uploads/2023/06/2022-10-28-F08-CC01-Landing_WEB-2_WIDE2.jpg"
thumbnail_url: "https://imgs.search.brave.com/aoWvGR1VXfAxoSQIDAtcXNLRvFKHIzQeegxTqeFjzj8/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/amV0c3Byb3BzLmNv/bS93cC1jb250ZW50/L3VwbG9hZHMvMjAy/My8wNi8yMDIyLTEw/LTI4LUYwOC1DQzAx/LUxhbmRpbmdfV0VC/LTJfV0lERTIuanBn"
source: jetsprops.com
favicon_url: "https://imgs.search.brave.com/evSyBuhkwi6f6gd3qdEFxK6mgSobrFy0h8HbF7dnpHg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMWQ2NDIwZjcz/YTQ5YTFhNjdlNmI3/OGEyOTY1NmUyOGJk/YWVlODQwODRmYzZi/MTgzYzVlNDEyYzBi/NDg1MzlkMS93d3cu/amV0c3Byb3BzLmNv/bS8"
hash: 1fc9e12c833f48d5
embed_ref: jetsprops.com-opu
app_id: images
skill_id: search`,
      parent_embed_id: "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e",
      embed_ids: null,
    },
    {
      embed_id: "83b4f9e0-8739-4a8f-add6-e18f68ef21b9",
      type: "image_result",
      content: `type: image_result
title: Stratolaunch ROC
source_page_url: "https://www.jetsprops.com/transport/stratolaunch-roc-the-worlds-largest-aircraft.html"
image_url: "https://www.jetsprops.com/wp-content/uploads/2023/06/2022-10-28-F08-CC01-Landing_WEB-1-scaled.jpg"
thumbnail_url: "https://imgs.search.brave.com/YAf7mjBfOALjaDcVVX3TirgyVQQFJxlsmQ2IDKA1UYU/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/amV0c3Byb3BzLmNv/bS93cC1jb250ZW50/L3VwbG9hZHMvMjAy/My8wNi8yMDIyLTEw/LTI4LUYwOC1DQzAx/LUxhbmRpbmdfV0VC/LTEtc2NhbGVkLmpw/Zw"
source: jetsprops.com
favicon_url: "https://imgs.search.brave.com/evSyBuhkwi6f6gd3qdEFxK6mgSobrFy0h8HbF7dnpHg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMWQ2NDIwZjcz/YTQ5YTFhNjdlNmI3/OGEyOTY1NmUyOGJk/YWVlODQwODRmYzZi/MTgzYzVlNDEyYzBi/NDg1MzlkMS93d3cu/amV0c3Byb3BzLmNv/bS8"
hash: e36d6fd5d5b24f50
embed_ref: jetsprops.com-XPl
app_id: images
skill_id: search`,
      parent_embed_id: "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e",
      embed_ids: null,
    },
    {
      embed_id: "169624f7-f9fa-4a76-8633-1308a5291027",
      type: "image_result",
      content: `type: image_result
title: cnet-stratolaunch-1
source_page_url: "https://www.cnet.com/pictures/meet-the-stratolaunch-the-worlds-largest-airplane/"
image_url: "https://www.cnet.com/a/img/resize/c7c6479e88631196be5839319a3736c6540d8585/hub/2017/06/05/fd06ba83-5364-4467-a460-906a1bc6a3f5/cnet-stratolaunch-1.jpg?auto=webp&width=1200"
thumbnail_url: "https://imgs.search.brave.com/k0KGZIEFcm5tpKIlvGmf3xP2hlTYIXZNSVesReQVHO8/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/Y25ldC5jb20vYS9p/bWcvcmVzaXplL2M3/YzY0NzllODg2MzEx/OTZiZTU4MzkzMTlh/MzczNmM2NTQwZDg1/ODUvaHViLzIwMTcv/MDYvMDUvZmQwNmJh/ODMtNTM2NC00NDY3/LWE0NjAtOTA2YTFi/YzZhM2Y1L2NuZXQt/c3RyYXRvbGF1bmNo/LTEuanBnP2F1dG89/d2VicCZ3aWR0aD0x/MjAw"
source: cnet.com
favicon_url: "https://imgs.search.brave.com/mWlG-6ikaw-opvXdUS2O5Ia2lYTwH6MNnfeV64-Abho/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYWVkNmIyYmM4/MmJlODJlZDJjYTBh/MWE2MmMwMmVkOTdk/OThhMmU4ZjE0MTY4/MzAxYTcyNjI5OGI5/OGJhN2NmYS93d3cu/Y25ldC5jb20v"
hash: 84a7176fd5f9bcb1
embed_ref: cnet.com-63o
app_id: images
skill_id: search`,
      parent_embed_id: "0cd8de03-8aa9-47e3-b2f9-2d5e098cee2e",
      embed_ids: null,
    },
    {
      embed_id: "8bf3382a-8b7d-475a-9907-9bf99d16316e",
      type: "image_result",
      content: `type: image_result
title: The AN-225 Antonov &quot;Mriya&quot; (&quot;Dream&quot;) aircraft was originally built to transport Soviet-era Buran space shuttles.
source_page_url: "https://www.space.com/buran-shuttle-carrier-plane-antonov-an-225-mriya-destroyed-russia-ukraine"
image_url: "https://cdn.mos.cms.futurecdn.net/QjA4FGLabxQFH2NUKvqcQa.jpg"
thumbnail_url: "https://imgs.search.brave.com/UsaJTT4AzJeW7HNq1Jdh1xHni61rKWwKp_mZSUIyyPc/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L1Fq/QTRGR0xhYnhRRkgy/TlVLdnFjUWEuanBn"
source: space.com
favicon_url: "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
hash: 04a643e4342acf35
embed_ref: space.com-EES
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "299f62b8-51be-4103-94c1-3fcacf754735",
      type: "image_result",
      content: `type: image_result
title: "The antonov-225 mriya super-heavy transport aircraft conducting its first flight carrying the soviet space shuttle, buran, may 1989."
source_page_url: "https://www.popularmechanics.com/military/aviation/a32162223/antonov-225-mriya/"
image_url: "https://hips.hearstapps.com/hmg-prod/images/gettyimages-170976636-1586986427.jpg?resize=2048:*"
thumbnail_url: "https://imgs.search.brave.com/H_CABnjBwJoiUQ4sJd29gcsvu3BOkejKwLp7XgH3v2s/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9oaXBz/LmhlYXJzdGFwcHMu/Y29tL2htZy1wcm9k/L2ltYWdlcy9nZXR0/eWltYWdlcy0xNzA5/NzY2MzYtMTU4Njk4/NjQyNy5qcGc_cmVz/aXplPTIwNDg6Kg"
source: popularmechanics.com
favicon_url: "https://imgs.search.brave.com/5eBdbfS4leOm-yjE9Fe8n0h_cYnErS4ebpThJv09j5Y/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvM2IxM2RhOTZl/NzQ1MGJmMGRmYTBl/NmM5NGRmYjk5Mzhm/YzQ1MGMwYzE5NjAw/ZGUwMDk1NDU3NmQy/OTFiZTMyNy93d3cu/cG9wdWxhcm1lY2hh/bmljcy5jb20v"
hash: 1f88d77de47c6d02
embed_ref: popularmechanics.com-kIm
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "b5d2d78b-cb58-4a4f-a5aa-237d04a2ad52",
      type: "image_result",
      content: `type: image_result
title: "The Mriya Antonov An-225, the World’s Largest Super Transporter Has King-Sized Capability"
source_page_url: "https://www.flexaircharters.com/news/aircraft/the-mriya-antonov-an-225-the-worlds-largest-super-transporter-has-king-sized-capability/"
image_url: "https://www.flexaircharters.com/wp-content/uploads/2018/07/the-mriya-antonov-an-225-the-worlds-largest-super-transporter-has-king-sized-capability.jpg"
thumbnail_url: "https://imgs.search.brave.com/ZQr26A2DkWOSQynZbwx-9o6SPfhzqhI6lUWta16b_Yg/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/ZmxleGFpcmNoYXJ0/ZXJzLmNvbS93cC1j/b250ZW50L3VwbG9h/ZHMvMjAxOC8wNy90/aGUtbXJpeWEtYW50/b25vdi1hbi0yMjUt/dGhlLXdvcmxkcy1s/YXJnZXN0LXN1cGVy/LXRyYW5zcG9ydGVy/LWhhcy1raW5nLXNp/emVkLWNhcGFiaWxp/dHkuanBn"
source: flexaircharters.com
favicon_url: "https://imgs.search.brave.com/Y5P7JG0VQKEqCZhlsQNLItw8nHY7nDvbxY8BhqaH2Jw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNzM2N2RkODQ4/ODVkY2Q2MTFjM2I5/NTI2MDBlMGJiMTRj/NmM2MjNkYmJiMzJl/MGQxNjQ1NmIwY2Ez/YWFlMjQ1Yi93d3cu/ZmxleGFpcmNoYXJ0/ZXJzLmNvbS8"
hash: 2de73bb6325628ea
embed_ref: flexaircharters.com-If5
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "f5339e36-2e68-4bc1-a7f4-bebfd8597837",
      type: "image_result",
      content: `type: image_result
title: "The Antonov AN-225 &quot;Mriya&quot; transports the Soviet-era Buran space shuttle orbiter piggyback, as the aircraft was originally designed to do."
source_page_url: "https://www.space.com/buran-shuttle-carrier-plane-antonov-an-225-mriya-destroyed-russia-ukraine"
image_url: "https://cdn.mos.cms.futurecdn.net/pEmaWbgP54aJFqSC8VRgLg.jpg"
thumbnail_url: "https://imgs.search.brave.com/YF6Txjbnkv2eYAKHb3c52s96Ni32V8mM24l8ql27DqM/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L3BF/bWFXYmdQNTRhSkZx/U0M4VlJnTGcuanBn"
source: space.com
favicon_url: "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
hash: b1cc652fe0b12b7e
embed_ref: space.com-8rC
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "299f62b8-51be-4103-94c1-3fcacf754735",
      type: "image_result",
      content: `type: image_result
title: "The antonov-225 mriya super-heavy transport aircraft conducting its first flight carrying the soviet space shuttle, buran, may 1989."
source_page_url: "https://www.popularmechanics.com/military/aviation/a32162223/antonov-225-mriya/"
image_url: "https://hips.hearstapps.com/hmg-prod/images/gettyimages-170976636-1586986427.jpg?resize=2048:*"
thumbnail_url: "https://imgs.search.brave.com/H_CABnjBwJoiUQ4sJd29gcsvu3BOkejKwLp7XgH3v2s/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9oaXBz/LmhlYXJzdGFwcHMu/Y29tL2htZy1wcm9k/L2ltYWdlcy9nZXR0/eWltYWdlcy0xNzA5/NzY2MzYtMTU4Njk4/NjQyNy5qcGc_cmVz/aXplPTIwNDg6Kg"
source: popularmechanics.com
favicon_url: "https://imgs.search.brave.com/5eBdbfS4leOm-yjE9Fe8n0h_cYnErS4ebpThJv09j5Y/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvM2IxM2RhOTZl/NzQ1MGJmMGRmYTBl/NmM5NGRmYjk5Mzhm/YzQ1MGMwYzE5NjAw/ZGUwMDk1NDU3NmQy/OTFiZTMyNy93d3cu/cG9wdWxhcm1lY2hh/bmljcy5jb20v"
hash: 1f88d77de47c6d02
embed_ref: popularmechanics.com-kIm
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "3a173c45-654c-4bae-88f1-b84ed4e9b635",
      type: "image_result",
      content: `type: image_result
title: Antonov An-225 Mriya cargo transporter
source_page_url: "https://www.britannica.com/technology/An-225-Mriya"
image_url: "https://cdn.britannica.com/31/60831-004-AB602BEB/cargo-transporter-Antonov-An-225-Mriya-Buran-orbiter-1988.jpg"
thumbnail_url: "https://imgs.search.brave.com/jCYJk8sfmrZljmla6nUDfDKBVRjKo-jKp6JeBBkvP5E/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/YnJpdGFubmljYS5j/b20vMzEvNjA4MzEt/MDA0LUFCNjAyQkVC/L2NhcmdvLXRyYW5z/cG9ydGVyLUFudG9u/b3YtQW4tMjI1LU1y/aXlhLUJ1cmFuLW9y/Yml0ZXItMTk4OC5q/cGc"
source: britannica.com
favicon_url: "https://imgs.search.brave.com/jMDHLEzOKBVbwQ7-d4wBSobNay75CY4fiZkxDsHYBkA/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNzJmYzgxOWRk/Y2FhNWI2MzQzMjQ4/MWVhZDZhNGY3ZjY0/MDgxZTM3YWU5MzYz/NGU2MzM3Y2Y2YTYz/M2IyM2Y0NC93d3cu/YnJpdGFubmljYS5j/b20v"
hash: d714119cf1dc66fa
embed_ref: britannica.com-f9U
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "f5339e36-2e68-4bc1-a7f4-bebfd8597837",
      type: "image_result",
      content: `type: image_result
title: "The Antonov AN-225 &quot;Mriya&quot; transports the Soviet-era Buran space shuttle orbiter piggyback, as the aircraft was originally designed to do."
source_page_url: "https://www.space.com/buran-shuttle-carrier-plane-antonov-an-225-mriya-destroyed-russia-ukraine"
image_url: "https://cdn.mos.cms.futurecdn.net/pEmaWbgP54aJFqSC8VRgLg.jpg"
thumbnail_url: "https://imgs.search.brave.com/YF6Txjbnkv2eYAKHb3c52s96Ni32V8mM24l8ql27DqM/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L3BF/bWFXYmdQNTRhSkZx/U0M4VlJnTGcuanBn"
source: space.com
favicon_url: "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
hash: b1cc652fe0b12b7e
embed_ref: space.com-8rC
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "8bf3382a-8b7d-475a-9907-9bf99d16316e",
      type: "image_result",
      content: `type: image_result
title: The AN-225 Antonov &quot;Mriya&quot; (&quot;Dream&quot;) aircraft was originally built to transport Soviet-era Buran space shuttles.
source_page_url: "https://www.space.com/buran-shuttle-carrier-plane-antonov-an-225-mriya-destroyed-russia-ukraine"
image_url: "https://cdn.mos.cms.futurecdn.net/QjA4FGLabxQFH2NUKvqcQa.jpg"
thumbnail_url: "https://imgs.search.brave.com/UsaJTT4AzJeW7HNq1Jdh1xHni61rKWwKp_mZSUIyyPc/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L1Fq/QTRGR0xhYnhRRkgy/TlVLdnFjUWEuanBn"
source: space.com
favicon_url: "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
hash: 04a643e4342acf35
embed_ref: space.com-EES
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "a95a3602-3009-494e-97d7-aa471ceb1297",
      type: "image_result",
      content: `type: image_result
title: "mriya, AN 225, Antonov 225, mriya 225, plane, cossack, big plane, transport, an-225, an-124, an-224, an-325, MAKS, sovietic, soviet, Буран, Энергия, antonov Airlines, antonov, constructor antonov, antonov design bureau, USSR, Le Bourget 1989, air show"
source_page_url: "https://www.buran-energia.com/mriya-antonov/mriya-desc.php"
image_url: "https://www.buran.fr/mriya-antonov/img/060-Sur%20le%20tarmac-On%20the%20macadam-000-petit.jpg"
thumbnail_url: "https://imgs.search.brave.com/xD4GUmXjoz4WROcVSEHgbIiBK4jxSvHcoyAo82G0ipA/rs:fit:0:180:1:0/g:ce/aHR0cHM6Ly93d3cu/YnVyYW4uZnIvbXJp/eWEtYW50b25vdi9p/bWcvMDYwLVN1ciUy/MGxlJTIwdGFybWFj/LU9uJTIwdGhlJTIw/bWFjYWRhbS0wMDAt/cGV0aXQuanBn"
source: buran-energia.com
favicon_url: "https://imgs.search.brave.com/W64kHjLUbXRol7P-AGZg-yOAMBAFuttoKVV8xJeZkoM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOWQxMzIyOTQz/NTYwNTkxMzFjZWRh/ODBkNjNlNDEwMjU1/MmUyOTg3MmQ0MzBh/ZDY1ODMxMTQ3MWZj/ZTI0NGM5My93d3cu/YnVyYW4tZW5lcmdp/YS5jb20v"
hash: e73f0aa8bbcd98a6
embed_ref: buran-energia.com-rGr
app_id: images
skill_id: search`,
      parent_embed_id: "a9f61cd9-09d1-4010-b720-fc60fe92e0c0",
      embed_ids: null,
    },
    {
      embed_id: "dabe894f-27c6-48b5-be0e-049da5533bb8",
      type: "website",
      content: `type: search_result
title: Huge weird airplane built to swallow spacecraft | CNN
url: "https://amp.cnn.com/cnn/travel/article/super-guppy-transporter-airplane/index.html"
description: "Airbus Beluga, Boeing Dreamlifter, Antonov AN-225: these are the names of some of the biggest aircraft in the world, designed to carry extremely large cargo, such as parts of other planes."
page_age: "December 9, 2020"
profile_name: CNN Underscored
meta_url_favicon: "https://imgs.search.brave.com/PGB6cMvl-q-qWSilWjhwwU6If-b7UNRGGRzNNOd0_mg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZmRjZDVkNGJh/NDlkMzY3NzY2MjQ4/NDdkMWUyZThkMzY1/OGJlZDk1NzBiMGU2/ZTkwNjg0MzdjOGZk/N2Y2ZmYyYy9hbXAu/Y25uLmNvbS8"
thumbnail_src: "https://imgs.search.brave.com/fqb_SJM86j3qPT9MJbq8TSOdNeOTlg0K6EBkIqD1AAM/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5jbm4uY29tL2Fw/aS92MS9pbWFnZXMv/c3RlbGxhci9wcm9k/LzIwMTIwNzE4NTMz/Ny1ndXBweS1ydW53/YXktMS5qcGc_cT14/XzAseV8wLGhfOTAw/LHdfMTU5OSxjX2Zp/bGwvd184MDA"
thumbnail_original: "https://media.cnn.com/api/v1/images/stellar/prod/201207185337-guppy-runway-1.jpg?q=x_0,y_0,h_900,w_1599,c_fill/w_800"
extra_snippets: "Conroy established a company, Aero Spacelines, to build and operate the plane, which ended up being 16 feet longer than the Boeing 377, and the only aircraft in the world capable of transporting the upper stage of a Saturn rocket for the Apollo program.|Airbus Beluga, Boeing Dreamlifter, Antonov AN-225: these are the names of some of the biggest aircraft in the world, designed to carry extremely large cargo, such as parts of other planes. Because of their rarity and their extraordinary appearance, they are the eye-catchers of the aviation world and a planespotter’s dream. But these aircraft wouldn’t exist without a lesser known series of planes that first flew in the 1960s and helped America win the space race. ... “NASA was trying to figure out a way of moving objects that were very light but very large – in other words, rocket components – from one side of the USA to the other,” says aviation historian Graham M.|Airbus purchased two Super Guppy turbines in the 1970s to transport parts for its A300 aircraft.|“They needed something that had a really large fuselage in diameter, so they could ship the parts from where they were building them, mainly California, to where they were using them, mainly Florida.” · The Aero Spaceline Pregnant Guppy preparing for flight tests in 1962. ... During the early years of America’s fledgling space program, rocket parts headed to Cape Kennedy had to go through the Panama Canal or the Gulf of Mexico on barges, adding weeks to an already frantic schedule."
hash: 8524e832c6a0fe7d
embed_ref: amp.cnn.com-cBS
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "acd8bfb7-944b-4cb9-84a9-0579762e1fb5",
      type: "website",
      content: `type: search_result
title: The incredible stories behind the world’s biggest planes | loveexploring.com
url: "https://www.loveexploring.com/gallerylist/74177/the-incredible-stories-behind-the-worlds-biggest-planes"
description: "Rather than transporting passengers, the Roc is designed to carry hypersonic vehicles and rockets to the cruising altitude of commercial aircraft and launch them into space. Stratolaunch Systems Corp. The gigantic aircraft is designed to be a reusable air launch platform."
page_age: "July 14, 2025"
profile_name: loveexploring.com
meta_url_favicon: "https://imgs.search.brave.com/DicMGRPEaqGZKygjAGW2SjYhU4WNZiJCPNHf932_OoI/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzMyMGU5MDA3/ZDZiZTYyMzBmYTUy/NDgzNWFjNTAzYTI2/NzlkM2MxMWVhZGRi/ZDVmNDVmYzIzMTU4/NDliNDFiNC93d3cu/bG92ZWV4cGxvcmlu/Zy5jb20v"
thumbnail: null
extra_snippets: "Rather than transporting passengers, the Roc is designed to carry hypersonic vehicles and rockets to the cruising altitude of commercial aircraft and launch them into space. Stratolaunch Systems Corp. The gigantic aircraft is designed to be a reusable air launch platform.|From wooden seaplanes built in the 1940s to the aircraft making space travel possible, we look at some of the world's most gigantic planes and the astonishing stories behind them. Click through the gallery to learn about the largest planes in history, ranked by wingspan from smallest to largest... ... With its 197-foot (60m) wingspan, the Airbus A-330-700 Beluga XL may be the smallest plane on our list but it’s certainly among the most eye-catching. Designed to resemble the whale it’s named after, the cargo plane is used to transport large parts for other aircraft from Airbus manufacturing sites across Europe.|As well as transporting bulky parts – including the Dreamliner’s wings – three of the Dreamlifters were called into service during the COVID-19 pandemic to carry vital medical supplies.|Despite its incredible size and almost-as-incredible cost, the gigantic plane was sadly not destined for a life in the skies."
hash: f5990886006202a0
embed_ref: loveexploring.com-Obn
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "50569a5b-55cf-4373-837f-eb53639334d6",
      type: "website",
      content: `type: search_result
title: Spaceplane - Wikipedia
url: "https://en.wikipedia.org/wiki/Spaceplane"
description: "Like its American counterpart, the Buran orbital vehicle, when in transit from its landing sites back to the launch complex, was transported on the back of a large jet aeroplane – the Antonov An-225 Mriya transport aircraft, which was designed ..."
page_age: "February 15, 2026"
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/HVQ7nJ9d_Jg4CLgnpBV3kGe3q4RsCh2S9JOPihjQ1uo/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy8x/LzFkL1NUUy0xMzNf/U3BhY2VfU2h1dHRs/ZV9EaXNjb3Zlcnlf/YWZ0ZXJfdW5kb2Nr/aW5nXzNfJTI4Y3Jv/cHBlZCUyOS5qcGc"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/1/1d/STS-133_Space_Shuttle_Discovery_after_undocking_3_%28cropped%29.jpg"
extra_snippets: "Like its American counterpart, the Buran orbital vehicle, when in transit from its landing sites back to the launch complex, was transported on the back of a large jet aeroplane – the Antonov An-225 Mriya transport aircraft, which was designed in part for this task and was the largest aircraft in the world to fly multiple times. Before the Mriya was ready (after the Buran had flown), the Myasishchev VM-T Atlant, a variant on the Soviet Myasishchev M-4 Molot (Hammer) bomber (NATO code: Bison), fulfilled the same role. The Soviet Union first considered a preliminary design of rocket-launch small spaceplane Lapotok in early 1960s.|It will be carried by a sounding rocket to apogee of approximately 130 km. Its first flight is expected in 2026. The German company POLARIS Spaceplanes, in cooperation with DLR, is developing a multipurpose suborbital spaceplane Aurora that can be used for launching payloads into orbit when combined with an expendable upper stage. Dassault Aviation and OHB are developing an orbital spaceplane called VORTEX (Véhicule Orbital Réutilisable de Transport et d’EXploration) for both civilian and military orbital missions.|The Spiral airspace system with small orbital spaceplane and rocket as second stage was developed in the 1960s–1980s. Mikoyan-Gurevich MiG-105 was a crewed test vehicle to explore low-speed handling and landing. In the early 2000s the orbital 'cosmoplane' (Russian: космоплан) was proposed by Russia's Institute of Applied Mechanics as a passenger transport.|The Multi-Unit Space Transport And Recovery Device (MUSTARD) was a concept explored by the British Aircraft Corporation (BAC) around 1968 for launching payloads weighing as much as 2,300 kg (5,000 lb) into orbit. It was never constructed. In the 1980s, British Aerospace began development of HOTOL, an SSTO spaceplane powered by a revolutionary SABRE air-breathing rocket engine, but the project was canceled due to technical and financial uncertainties.|The Sänger II had predicted cost savings of up to 30 percent over expendable rockets. Hopper was one of several proposals for a European reusable launch vehicle (RLV) planned to cheaply ferry satellites into orbit by 2015. One of those was 'Phoenix', a German project which is a one-seventh scale model of the Hopper concept vehicle. The suborbital Hopper was a Future European Space Transportation Investigations Programme system study design A test project, the Intermediate eXperimental Vehicle (IXV), has demonstrated lifting reentry technologies and will be extended under the PRIDE programme."
hash: cc800b5c14f19351
embed_ref: en.wikipedia.org-1bC
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "29c80a78-7114-4864-a0c2-e63beea213c0",
      type: "website",
      content: `type: search_result
title: List of rocket-powered aircraft - Wikipedia
url: "https://en.wikipedia.org/wiki/List_of_rocket-powered_aircraft"
description: "A rocket-powered aircraft or rocket plane is an aircraft that uses a rocket engine for propulsion, sometimes in addition to airbreathing jet engines. Rocket planes can achieve much higher speeds than similarly sized jet aircraft, but typically for at most a few minutes of powered operation, ..."
page_age: "February 18, 2026"
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail: null
extra_snippets: "Unhindered by the need for oxygen from the atmosphere, they are suitable for very high-altitude flight. They are also capable of delivering much higher acceleration and shorter takeoffs. Many rocket aircraft may be drop launched from transport planes, as take-off from ground may leave them with insufficient time to reach high altitudes."
hash: 2b03fc74bd86055c
embed_ref: en.wikipedia.org-sGG
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "dabe894f-27c6-48b5-be0e-049da5533bb8",
      type: "website",
      content: `type: search_result
title: Huge weird airplane built to swallow spacecraft | CNN
url: "https://amp.cnn.com/cnn/travel/article/super-guppy-transporter-airplane/index.html"
description: "Airbus Beluga, Boeing Dreamlifter, Antonov AN-225: these are the names of some of the biggest aircraft in the world, designed to carry extremely large cargo, such as parts of other planes."
page_age: "December 9, 2020"
profile_name: CNN Underscored
meta_url_favicon: "https://imgs.search.brave.com/PGB6cMvl-q-qWSilWjhwwU6If-b7UNRGGRzNNOd0_mg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZmRjZDVkNGJh/NDlkMzY3NzY2MjQ4/NDdkMWUyZThkMzY1/OGJlZDk1NzBiMGU2/ZTkwNjg0MzdjOGZk/N2Y2ZmYyYy9hbXAu/Y25uLmNvbS8"
thumbnail_src: "https://imgs.search.brave.com/fqb_SJM86j3qPT9MJbq8TSOdNeOTlg0K6EBkIqD1AAM/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9tZWRp/YS5jbm4uY29tL2Fw/aS92MS9pbWFnZXMv/c3RlbGxhci9wcm9k/LzIwMTIwNzE4NTMz/Ny1ndXBweS1ydW53/YXktMS5qcGc_cT14/XzAseV8wLGhfOTAw/LHdfMTU5OSxjX2Zp/bGwvd184MDA"
thumbnail_original: "https://media.cnn.com/api/v1/images/stellar/prod/201207185337-guppy-runway-1.jpg?q=x_0,y_0,h_900,w_1599,c_fill/w_800"
extra_snippets: "Conroy established a company, Aero Spacelines, to build and operate the plane, which ended up being 16 feet longer than the Boeing 377, and the only aircraft in the world capable of transporting the upper stage of a Saturn rocket for the Apollo program.|Airbus Beluga, Boeing Dreamlifter, Antonov AN-225: these are the names of some of the biggest aircraft in the world, designed to carry extremely large cargo, such as parts of other planes. Because of their rarity and their extraordinary appearance, they are the eye-catchers of the aviation world and a planespotter’s dream. But these aircraft wouldn’t exist without a lesser known series of planes that first flew in the 1960s and helped America win the space race. ... “NASA was trying to figure out a way of moving objects that were very light but very large – in other words, rocket components – from one side of the USA to the other,” says aviation historian Graham M.|Airbus purchased two Super Guppy turbines in the 1970s to transport parts for its A300 aircraft.|“They needed something that had a really large fuselage in diameter, so they could ship the parts from where they were building them, mainly California, to where they were using them, mainly Florida.” · The Aero Spaceline Pregnant Guppy preparing for flight tests in 1962. ... During the early years of America’s fledgling space program, rocket parts headed to Cape Kennedy had to go through the Panama Canal or the Gulf of Mexico on barges, adding weeks to an already frantic schedule."
hash: 8524e832c6a0fe7d
embed_ref: amp.cnn.com-cBS
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "29c80a78-7114-4864-a0c2-e63beea213c0",
      type: "website",
      content: `type: search_result
title: List of rocket-powered aircraft - Wikipedia
url: "https://en.wikipedia.org/wiki/List_of_rocket-powered_aircraft"
description: "A rocket-powered aircraft or rocket plane is an aircraft that uses a rocket engine for propulsion, sometimes in addition to airbreathing jet engines. Rocket planes can achieve much higher speeds than similarly sized jet aircraft, but typically for at most a few minutes of powered operation, ..."
page_age: "February 18, 2026"
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail: null
extra_snippets: "Unhindered by the need for oxygen from the atmosphere, they are suitable for very high-altitude flight. They are also capable of delivering much higher acceleration and shorter takeoffs. Many rocket aircraft may be drop launched from transport planes, as take-off from ground may leave them with insufficient time to reach high altitudes."
hash: 2b03fc74bd86055c
embed_ref: en.wikipedia.org-sGG
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "710a4efd-2208-41fb-a14c-e4ba7e530b5e",
      type: "website",
      content: `type: search_result
title: Rocket-powered aircraft - Wikipedia
url: "https://en.wikipedia.org/wiki/Rocket-powered_aircraft"
description: "For their work, the SpaceShipOne team were awarded the Space Achievement Award. In April 2019, the Chinese company Space Transportation carried out a test of a 3,700-kilogram technology demonstrator named Jiageng-1. The 8.7-meter-long plane ..."
page_age: "March 3, 2026"
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/-pDcf8PMOpJfNjuvO47hO8a8GVu1nOEknosoah87OLE/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy81/LzU2L01lMTYzZWZK/TS5qcGc"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/5/56/Me163efJM.jpg"
extra_snippets: "SpaceShipOne functions both as a rocket-powered aircraft—with wings and aerodynamic control surfaces—as well as a spaceplane—with RCS thrusters for control in the vacuum of space. For their work, the SpaceShipOne team were awarded the Space Achievement Award. In April 2019, the Chinese company Space Transportation carried out a test of a 3,700-kilogram technology demonstrator named Jiageng-1. The 8.7-meter-long plane has a wingspan of 2.5 meters and it is a part of development of the larger, future Tianxing-I-1 vertical takeoff, horizontal landing reusable launch vehicle.|The EZ-Rocket research and test airplane was first flown in 2001.|Unhindered by the need for oxygen from the atmosphere, they are suitable for very high-altitude flight. They are also capable of delivering much higher acceleration and shorter takeoffs. Many rocket aircraft may be drop launched from transport planes, as take-off from ground may leave them with insufficient time to reach high altitudes.|Paulet would soon be approached by Nazi Germany to help develop rocket technology, though he refused to assist and never shared the formula for his propellant. The Nazi government would then appropriate Paulet's work while a Soviet spy in the VfR, Alexander Boris Scherchevsky, possibly shared plans with the Soviet Union. On 11 June 1928, as part of the Opel RAK program of Fritz von Opel and Max Valier, Lippisch Ente became the first aircraft to fly under rocket power.|On 28 June 1931, another ground-breaking rocket flight was conducted by the Italian aviator and inventor Ettore Cattaneo, who created another privately built rocket plane. It flew and landed without particular problems."
hash: 5f3c8e8a6308ae77
embed_ref: en.wikipedia.org-9uc
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "710a4efd-2208-41fb-a14c-e4ba7e530b5e",
      type: "website",
      content: `type: search_result
title: Rocket-powered aircraft - Wikipedia
url: "https://en.wikipedia.org/wiki/Rocket-powered_aircraft"
description: "For their work, the SpaceShipOne team were awarded the Space Achievement Award. In April 2019, the Chinese company Space Transportation carried out a test of a 3,700-kilogram technology demonstrator named Jiageng-1. The 8.7-meter-long plane ..."
page_age: "March 3, 2026"
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/-pDcf8PMOpJfNjuvO47hO8a8GVu1nOEknosoah87OLE/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy81/LzU2L01lMTYzZWZK/TS5qcGc"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/5/56/Me163efJM.jpg"
extra_snippets: "SpaceShipOne functions both as a rocket-powered aircraft—with wings and aerodynamic control surfaces—as well as a spaceplane—with RCS thrusters for control in the vacuum of space. For their work, the SpaceShipOne team were awarded the Space Achievement Award. In April 2019, the Chinese company Space Transportation carried out a test of a 3,700-kilogram technology demonstrator named Jiageng-1. The 8.7-meter-long plane has a wingspan of 2.5 meters and it is a part of development of the larger, future Tianxing-I-1 vertical takeoff, horizontal landing reusable launch vehicle.|The EZ-Rocket research and test airplane was first flown in 2001.|Unhindered by the need for oxygen from the atmosphere, they are suitable for very high-altitude flight. They are also capable of delivering much higher acceleration and shorter takeoffs. Many rocket aircraft may be drop launched from transport planes, as take-off from ground may leave them with insufficient time to reach high altitudes.|Paulet would soon be approached by Nazi Germany to help develop rocket technology, though he refused to assist and never shared the formula for his propellant. The Nazi government would then appropriate Paulet's work while a Soviet spy in the VfR, Alexander Boris Scherchevsky, possibly shared plans with the Soviet Union. On 11 June 1928, as part of the Opel RAK program of Fritz von Opel and Max Valier, Lippisch Ente became the first aircraft to fly under rocket power.|On 28 June 1931, another ground-breaking rocket flight was conducted by the Italian aviator and inventor Ettore Cattaneo, who created another privately built rocket plane. It flew and landed without particular problems."
hash: 5f3c8e8a6308ae77
embed_ref: en.wikipedia.org-9uc
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      type: "app_skill_use",
      content: `app_id: web
skill_id: search
result_count: 6
embed_ids: 710a4efd-2208-41fb-a14c-e4ba7e530b5e|acd8bfb7-944b-4cb9-84a9-0579762e1fb5|dabe894f-27c6-48b5-be0e-049da5533bb8|bfeb1f8d-3bee-490e-9343-a91e1fb366fe|29c80a78-7114-4864-a0c2-e63beea213c0|50569a5b-55cf-4373-837f-eb53639334d6
status: finished
query: gigantic airplane used to transport rocket parts name
provider: Brave`,
      parent_embed_id: null,
      embed_ids: ["710a4efd-2208-41fb-a14c-e4ba7e530b5e", "acd8bfb7-944b-4cb9-84a9-0579762e1fb5", "dabe894f-27c6-48b5-be0e-049da5533bb8", "bfeb1f8d-3bee-490e-9343-a91e1fb366fe", "29c80a78-7114-4864-a0c2-e63beea213c0", "50569a5b-55cf-4373-837f-eb53639334d6"],
    },
    {
      embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      type: "app_skill_use",
      content: `app_id: web
skill_id: search
result_count: 6
embed_ids: 710a4efd-2208-41fb-a14c-e4ba7e530b5e|acd8bfb7-944b-4cb9-84a9-0579762e1fb5|dabe894f-27c6-48b5-be0e-049da5533bb8|bfeb1f8d-3bee-490e-9343-a91e1fb366fe|29c80a78-7114-4864-a0c2-e63beea213c0|50569a5b-55cf-4373-837f-eb53639334d6
status: finished
query: gigantic airplane used to transport rocket parts name
provider: Brave`,
      parent_embed_id: null,
      embed_ids: ["710a4efd-2208-41fb-a14c-e4ba7e530b5e", "acd8bfb7-944b-4cb9-84a9-0579762e1fb5", "dabe894f-27c6-48b5-be0e-049da5533bb8", "bfeb1f8d-3bee-490e-9343-a91e1fb366fe", "29c80a78-7114-4864-a0c2-e63beea213c0", "50569a5b-55cf-4373-837f-eb53639334d6"],
    },
    {
      embed_id: "50569a5b-55cf-4373-837f-eb53639334d6",
      type: "website",
      content: `type: search_result
title: Spaceplane - Wikipedia
url: "https://en.wikipedia.org/wiki/Spaceplane"
description: "Like its American counterpart, the Buran orbital vehicle, when in transit from its landing sites back to the launch complex, was transported on the back of a large jet aeroplane – the Antonov An-225 Mriya transport aircraft, which was designed ..."
page_age: "February 15, 2026"
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/HVQ7nJ9d_Jg4CLgnpBV3kGe3q4RsCh2S9JOPihjQ1uo/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy8x/LzFkL1NUUy0xMzNf/U3BhY2VfU2h1dHRs/ZV9EaXNjb3Zlcnlf/YWZ0ZXJfdW5kb2Nr/aW5nXzNfJTI4Y3Jv/cHBlZCUyOS5qcGc"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/1/1d/STS-133_Space_Shuttle_Discovery_after_undocking_3_%28cropped%29.jpg"
extra_snippets: "Like its American counterpart, the Buran orbital vehicle, when in transit from its landing sites back to the launch complex, was transported on the back of a large jet aeroplane – the Antonov An-225 Mriya transport aircraft, which was designed in part for this task and was the largest aircraft in the world to fly multiple times. Before the Mriya was ready (after the Buran had flown), the Myasishchev VM-T Atlant, a variant on the Soviet Myasishchev M-4 Molot (Hammer) bomber (NATO code: Bison), fulfilled the same role. The Soviet Union first considered a preliminary design of rocket-launch small spaceplane Lapotok in early 1960s.|It will be carried by a sounding rocket to apogee of approximately 130 km. Its first flight is expected in 2026. The German company POLARIS Spaceplanes, in cooperation with DLR, is developing a multipurpose suborbital spaceplane Aurora that can be used for launching payloads into orbit when combined with an expendable upper stage. Dassault Aviation and OHB are developing an orbital spaceplane called VORTEX (Véhicule Orbital Réutilisable de Transport et d’EXploration) for both civilian and military orbital missions.|The Spiral airspace system with small orbital spaceplane and rocket as second stage was developed in the 1960s–1980s. Mikoyan-Gurevich MiG-105 was a crewed test vehicle to explore low-speed handling and landing. In the early 2000s the orbital 'cosmoplane' (Russian: космоплан) was proposed by Russia's Institute of Applied Mechanics as a passenger transport.|The Multi-Unit Space Transport And Recovery Device (MUSTARD) was a concept explored by the British Aircraft Corporation (BAC) around 1968 for launching payloads weighing as much as 2,300 kg (5,000 lb) into orbit. It was never constructed. In the 1980s, British Aerospace began development of HOTOL, an SSTO spaceplane powered by a revolutionary SABRE air-breathing rocket engine, but the project was canceled due to technical and financial uncertainties.|The Sänger II had predicted cost savings of up to 30 percent over expendable rockets. Hopper was one of several proposals for a European reusable launch vehicle (RLV) planned to cheaply ferry satellites into orbit by 2015. One of those was 'Phoenix', a German project which is a one-seventh scale model of the Hopper concept vehicle. The suborbital Hopper was a Future European Space Transportation Investigations Programme system study design A test project, the Intermediate eXperimental Vehicle (IXV), has demonstrated lifting reentry technologies and will be extended under the PRIDE programme."
hash: cc800b5c14f19351
embed_ref: en.wikipedia.org-1bC
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "acd8bfb7-944b-4cb9-84a9-0579762e1fb5",
      type: "website",
      content: `type: search_result
title: The incredible stories behind the world’s biggest planes | loveexploring.com
url: "https://www.loveexploring.com/gallerylist/74177/the-incredible-stories-behind-the-worlds-biggest-planes"
description: "Rather than transporting passengers, the Roc is designed to carry hypersonic vehicles and rockets to the cruising altitude of commercial aircraft and launch them into space. Stratolaunch Systems Corp. The gigantic aircraft is designed to be a reusable air launch platform."
page_age: "July 14, 2025"
profile_name: loveexploring.com
meta_url_favicon: "https://imgs.search.brave.com/DicMGRPEaqGZKygjAGW2SjYhU4WNZiJCPNHf932_OoI/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzMyMGU5MDA3/ZDZiZTYyMzBmYTUy/NDgzNWFjNTAzYTI2/NzlkM2MxMWVhZGRi/ZDVmNDVmYzIzMTU4/NDliNDFiNC93d3cu/bG92ZWV4cGxvcmlu/Zy5jb20v"
thumbnail: null
extra_snippets: "Rather than transporting passengers, the Roc is designed to carry hypersonic vehicles and rockets to the cruising altitude of commercial aircraft and launch them into space. Stratolaunch Systems Corp. The gigantic aircraft is designed to be a reusable air launch platform.|From wooden seaplanes built in the 1940s to the aircraft making space travel possible, we look at some of the world's most gigantic planes and the astonishing stories behind them. Click through the gallery to learn about the largest planes in history, ranked by wingspan from smallest to largest... ... With its 197-foot (60m) wingspan, the Airbus A-330-700 Beluga XL may be the smallest plane on our list but it’s certainly among the most eye-catching. Designed to resemble the whale it’s named after, the cargo plane is used to transport large parts for other aircraft from Airbus manufacturing sites across Europe.|As well as transporting bulky parts – including the Dreamliner’s wings – three of the Dreamlifters were called into service during the COVID-19 pandemic to carry vital medical supplies.|Despite its incredible size and almost-as-incredible cost, the gigantic plane was sadly not destined for a life in the skies."
hash: f5990886006202a0
embed_ref: loveexploring.com-Obn
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "bfeb1f8d-3bee-490e-9343-a91e1fb366fe",
      type: "website",
      content: `type: search_result
title: US Rocketplanes
url: "http://www.astronautix.com/u/usrocketplanes.html"
description: "Subtopics XS-1 American manned rocketplane. Design begun 1943. Also known as the X-1. This rocket plane was the first aircraft to break the sound barrier, and the first in a line of X- aircraft leading to the space shuttle. MX-324 Northrop manned rocketplane."
page_age: ""
profile_name: Encyclopedia Astronautica
meta_url_favicon: "https://imgs.search.brave.com/YJm7kKgfYIV8n5KlDv7WjtvmdO67qcLGIEk9LWByZV4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvM2Y3MzI2OTUx/ZTA3YTY4YWU5Y2M0/M2JlNGZhMTAyZjA0/NDUwMThhMWY3YjQ1/ZWYzZjg4YjFhNmY5/NTBkM2JiMi93d3cu/YXN0cm9uYXV0aXgu/Y29tLw"
thumbnail: null
extra_snippets[0]:
hash: e5c7ce87035824c8
embed_ref: astronautix.com-O7J
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
    {
      embed_id: "bfeb1f8d-3bee-490e-9343-a91e1fb366fe",
      type: "website",
      content: `type: search_result
title: US Rocketplanes
url: "http://www.astronautix.com/u/usrocketplanes.html"
description: "Subtopics XS-1 American manned rocketplane. Design begun 1943. Also known as the X-1. This rocket plane was the first aircraft to break the sound barrier, and the first in a line of X- aircraft leading to the space shuttle. MX-324 Northrop manned rocketplane."
page_age: ""
profile_name: Encyclopedia Astronautica
meta_url_favicon: "https://imgs.search.brave.com/YJm7kKgfYIV8n5KlDv7WjtvmdO67qcLGIEk9LWByZV4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvM2Y3MzI2OTUx/ZTA3YTY4YWU5Y2M0/M2JlNGZhMTAyZjA0/NDUwMThhMWY3YjQ1/ZWYzZjg4YjFhNmY5/NTBkM2JiMi93d3cu/YXN0cm9uYXV0aXgu/Y29tLw"
thumbnail: null
extra_snippets[0]:
hash: e5c7ce87035824c8
embed_ref: astronautix.com-O7J
app_id: web
skill_id: search`,
      parent_embed_id: "c71ba783-237b-4f89-8034-a44bd560fe65",
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 1,
  },
};