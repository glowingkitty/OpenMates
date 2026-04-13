// frontend/packages/ui/src/demo_chats/data/example_chats/artemis-ii-mission.ts
//
// Example chat: Artemis II Mission Highlights and Exploration
// Extracted from shared chat 1578a56f-bc3e-4069-816c-4fb5f3ee09fa
//
// Real conversation about the Artemis II mission, crew, milestones,
// and photo highlights with web search and image search results.

import type { ExampleChat } from "../../types";

export const artemisIIMissionChat: ExampleChat = {
  chat_id: "example-artemis-ii-mission",
  slug: "artemis-ii-mission-highlights",
  title: "example_chats.artemis_ii_mission.title",
  summary: "example_chats.artemis_ii_mission.summary",
  icon: "rocket",
  category: "science",
  keywords: [
    "Artemis II", "NASA", "moon mission", "space exploration",
    "Orion spacecraft", "astronauts", "lunar orbit", "SLS rocket"
  ],
  follow_up_suggestions: [
    "example_chats.artemis_ii_mission.follow_up_1",
    "example_chats.artemis_ii_mission.follow_up_2",
    "example_chats.artemis_ii_mission.follow_up_3",
    "example_chats.artemis_ii_mission.follow_up_4"
  ],
  messages: [
    {
      id: "b5f3ee09fa-64e3c950-585e-4b3b-b2ba-473839523bd9",
      role: "user",
      content: "example_chats.artemis_ii_mission.user_message_1",
      created_at: 1775996092,
      category: "science",
    },
    {
      id: "60e6b1df-26f8-4eec-8f42-7e5bca0a6909",
      role: "assistant",
      content: "example_chats.artemis_ii_mission.assistant_message_2",
      created_at: 1775996106,
      category: "science",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "dad76448-66cf-4cf3-bed6-d6ac0366ff1b",
      type: "image_result",
      content: `type: image_result
title: Artemis II Launches Manned Test Flight Around The Moon
source_page_url: "https://www.cbsnews.com/news/artemis-ii-moon-mission-highlights/"
image_url: "https://assets1.cbsnewsstatic.com/hub/i/r/2026/04/09/0531bb28-0ba5-4980-988b-3347c304e095/thumbnail/620x465/845eb4e8f43e7cfb1eca50e505989820/gettyimages-2269802288.jpg#"
thumbnail_url: "https://imgs.search.brave.com/DRdRk8eerr_sF0v2I_ljwIjLNeKARvFfniqNeQqq2z4/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9hc3Nl/dHMxLmNic25ld3Nz/dGF0aWMuY29tL2h1/Yi9pL3IvMjAyNi8w/NC8wOS8wNTMxYmIy/OC0wYmE1LTQ5ODAt/OTg4Yi0zMzQ3YzMw/NGUwOTUvdGh1bWJu/YWlsLzYyMHg0NjUv/ODQ1ZWI0ZThmNDNl/N2NmYjFlY2E1MGU1/MDU5ODk4MjAvZ2V0/dHlpbWFnZXMtMjI2/OTgwMjI4OC5qcGcj"
source: cbsnews.com
favicon_url: "https://imgs.search.brave.com/WMJ84WFf8h1hcjjVVUUmzl0nnJIhOkOa5cdJGjXcdWk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDUwNTNjY2I0/ZTJkMTA1NjkzNzQ3/Mzg4OGQ4ZDNmZjg0/YTFmYzhhZjBkMTU2/N2ZkNDA4MmZjZTM4/YTI3MTllMS93d3cu/Y2JzbmV3cy5jb20v"
hash: 623113da7ac48838
embed_ref: cbsnews.com-UIH
app_id: images
skill_id: search`,
      parent_embed_id: "36ad23c6-4f10-4122-9261-006a40deafc1",
      embed_ids: null,
    },
    {
      embed_id: "36ad23c6-4f10-4122-9261-006a40deafc1",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: dad76448-66cf-4cf3-bed6-d6ac0366ff1b|8864797d-39dd-4e66-ae00-7942394b75cb|ba3d0eba-fa22-4d73-819c-84f01d8cd97c|ab0df5bf-e800-4865-a688-df660cb8f2ab|234748ae-66c9-4e0f-b784-b957524fff83|cc47ac94-cd86-4b9e-a9d9-ffa91177bf35
status: finished
query: Artemis II mission highlights and graphics
id: 3
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["dad76448-66cf-4cf3-bed6-d6ac0366ff1b", "8864797d-39dd-4e66-ae00-7942394b75cb", "ba3d0eba-fa22-4d73-819c-84f01d8cd97c", "ab0df5bf-e800-4865-a688-df660cb8f2ab", "234748ae-66c9-4e0f-b784-b957524fff83", "cc47ac94-cd86-4b9e-a9d9-ffa91177bf35"],
    },
    {
      embed_id: "cc47ac94-cd86-4b9e-a9d9-ffa91177bf35",
      type: "image_result",
      content: `type: image_result
title: 019A1213.NEF
source_page_url: "https://www.nasa.gov/gallery/artemis-ii-flight-day-highlights/"
image_url: "https://images-assets.nasa.gov/image/art002e016172/art002e016172~large.jpg?w=1920&h=1280&fit=clip&crop=faces,focalpoint"
thumbnail_url: "https://imgs.search.brave.com/ZfgDNkl91QS9MRgmoH2DijRu1vVSdJIpr30br2CI9_w/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMtYXNzZXRzLm5h/c2EuZ292L2ltYWdl/L2FydDAwMmUwMTYx/NzIvYXJ0MDAyZTAx/NjE3Mn5sYXJnZS5q/cGc_dz0xOTIwJmg9/MTI4MCZmaXQ9Y2xp/cCZjcm9wPWZhY2Vz/LGZvY2FscG9pbnQ"
source: nasa.gov
favicon_url: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
hash: 4be5234d5c1870a9
embed_ref: nasa.gov-Mm8
app_id: images
skill_id: search`,
      parent_embed_id: "36ad23c6-4f10-4122-9261-006a40deafc1",
      embed_ids: null,
    },
    {
      embed_id: "234748ae-66c9-4e0f-b784-b957524fff83",
      type: "image_result",
      content: `type: image_result
title: Artemis II Launches Manned Test Flight Around The Moon
source_page_url: "https://www.cbsnews.com/news/artemis-ii-moon-mission-highlights/"
image_url: "https://assets1.cbsnewsstatic.com/hub/i/r/2026/04/09/0531bb28-0ba5-4980-988b-3347c304e095/thumbnail/96x96/71aa0242b1ad6aab86a91aa87349a25f/gettyimages-2269802288.jpg#"
thumbnail_url: "https://imgs.search.brave.com/4PjP9v51fj-4WqnzB2bRLyI0By8MygYHKLGuto0mS0E/rs:fit:0:180:1:0/g:ce/aHR0cHM6Ly9hc3Nl/dHMxLmNic25ld3Nz/dGF0aWMuY29tL2h1/Yi9pL3IvMjAyNi8w/NC8wOS8wNTMxYmIy/OC0wYmE1LTQ5ODAt/OTg4Yi0zMzQ3YzMw/NGUwOTUvdGh1bWJu/YWlsLzk2eDk2Lzcx/YWEwMjQyYjFhZDZh/YWI4NmE5MWFhODcz/NDlhMjVmL2dldHR5/aW1hZ2VzLTIyNjk4/MDIyODguanBnIw"
source: cbsnews.com
favicon_url: "https://imgs.search.brave.com/WMJ84WFf8h1hcjjVVUUmzl0nnJIhOkOa5cdJGjXcdWk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDUwNTNjY2I0/ZTJkMTA1NjkzNzQ3/Mzg4OGQ4ZDNmZjg0/YTFmYzhhZjBkMTU2/N2ZkNDA4MmZjZTM4/YTI3MTllMS93d3cu/Y2JzbmV3cy5jb20v"
hash: a98020e5349edae3
embed_ref: cbsnews.com-lsO
app_id: images
skill_id: search`,
      parent_embed_id: "36ad23c6-4f10-4122-9261-006a40deafc1",
      embed_ids: null,
    },
    {
      embed_id: "ab0df5bf-e800-4865-a688-df660cb8f2ab",
      type: "image_result",
      content: `type: image_result
title: ""
source_page_url: "https://www.cbsnews.com/news/artemis-ii-moon-mission-highlights/"
image_url: "https://substackcdn.com/image/fetch/$s_!u4dO!,f_auto,q_auto:good,fl_progressive:steep/https://substack-post-media.s3.amazonaws.com/public/images/cd3ef3db-7415-4a3e-a040-4d5b782ed0fd_1024x768.jpeg#"
thumbnail_url: "https://imgs.search.brave.com/n4mw1gAlmoO6Io7_CKL2qRTzRRCUhk-zMhQaW1aVWnE/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9zdWJz/dGFja2Nkbi5jb20v/aW1hZ2UvZmV0Y2gv/JHNfIXU0ZE8hLGZf/YXV0byxxX2F1dG86/Z29vZCxmbF9wcm9n/cmVzc2l2ZTpzdGVl/cC9odHRwczovL3N1/YnN0YWNrLXBvc3Qt/bWVkaWEuczMuYW1h/em9uYXdzLmNvbS9w/dWJsaWMvaW1hZ2Vz/L2NkM2VmM2RiLTc0/MTUtNGEzZS1hMDQw/LTRkNWI3ODJlZDBm/ZF8xMDI0eDc2OC5q/cGVnIw"
source: cbsnews.com
favicon_url: "https://imgs.search.brave.com/WMJ84WFf8h1hcjjVVUUmzl0nnJIhOkOa5cdJGjXcdWk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDUwNTNjY2I0/ZTJkMTA1NjkzNzQ3/Mzg4OGQ4ZDNmZjg0/YTFmYzhhZjBkMTU2/N2ZkNDA4MmZjZTM4/YTI3MTllMS93d3cu/Y2JzbmV3cy5jb20v"
hash: 61f70ac8cef7102e
embed_ref: cbsnews.com-x6A
app_id: images
skill_id: search`,
      parent_embed_id: "36ad23c6-4f10-4122-9261-006a40deafc1",
      embed_ids: null,
    },
    {
      embed_id: "ba3d0eba-fa22-4d73-819c-84f01d8cd97c",
      type: "image_result",
      content: `type: image_result
title: Earth seen from space on Artemis II mission
source_page_url: "https://www.cbsnews.com/news/artemis-ii-moon-mission-highlights/"
image_url: "https://assets1.cbsnewsstatic.com/hub/i/r/2026/04/03/86ac8f4b-80b7-483a-b6d3-30b3f2fc7d8c/thumbnail/620x409/fa1bf41ecdd8d5ba4b8d3ab3532d3dcd/ap26093499359031.jpg#"
thumbnail_url: "https://imgs.search.brave.com/euyVPHi-OugUX6WFx_WMbQPM8siyMSuT48TsOlQ059c/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9hc3Nl/dHMxLmNic25ld3Nz/dGF0aWMuY29tL2h1/Yi9pL3IvMjAyNi8w/NC8wMy84NmFjOGY0/Yi04MGI3LTQ4M2Et/YjZkMy0zMGIzZjJm/YzdkOGMvdGh1bWJu/YWlsLzYyMHg0MDkv/ZmExYmY0MWVjZGQ4/ZDViYTRiOGQzYWIz/NTMyZDNkY2QvYXAy/NjA5MzQ5OTM1OTAz/MS5qcGcj"
source: cbsnews.com
favicon_url: "https://imgs.search.brave.com/WMJ84WFf8h1hcjjVVUUmzl0nnJIhOkOa5cdJGjXcdWk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDUwNTNjY2I0/ZTJkMTA1NjkzNzQ3/Mzg4OGQ4ZDNmZjg0/YTFmYzhhZjBkMTU2/N2ZkNDA4MmZjZTM4/YTI3MTllMS93d3cu/Y2JzbmV3cy5jb20v"
hash: 02f6eaf758286b75
embed_ref: cbsnews.com-H7E
app_id: images
skill_id: search`,
      parent_embed_id: "36ad23c6-4f10-4122-9261-006a40deafc1",
      embed_ids: null,
    },
    {
      embed_id: "8864797d-39dd-4e66-ae00-7942394b75cb",
      type: "image_result",
      content: `type: image_result
title: Artemis II Launches Manned Test Flight Around The Moon
source_page_url: "https://www.cbsnews.com/news/artemis-ii-moon-mission-highlights/"
image_url: "https://assets3.cbsnewsstatic.com/hub/i/r/2026/04/10/f938b5eb-7856-4d6a-a6c0-099d1e018102/thumbnail/620x413/c2375f3a1e5f02f212ddd378050f7b26/gettyimages-2269802002.jpg#"
thumbnail_url: "https://imgs.search.brave.com/MAvWwJJza56PQhsO6yLF0xm3rcLyr4KxoZihBaBTLPs/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9hc3Nl/dHMzLmNic25ld3Nz/dGF0aWMuY29tL2h1/Yi9pL3IvMjAyNi8w/NC8xMC9mOTM4YjVl/Yi03ODU2LTRkNmEt/YTZjMC0wOTlkMWUw/MTgxMDIvdGh1bWJu/YWlsLzYyMHg0MTMv/YzIzNzVmM2ExZTVm/MDJmMjEyZGRkMzc4/MDUwZjdiMjYvZ2V0/dHlpbWFnZXMtMjI2/OTgwMjAwMi5qcGcj"
source: cbsnews.com
favicon_url: "https://imgs.search.brave.com/WMJ84WFf8h1hcjjVVUUmzl0nnJIhOkOa5cdJGjXcdWk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDUwNTNjY2I0/ZTJkMTA1NjkzNzQ3/Mzg4OGQ4ZDNmZjg0/YTFmYzhhZjBkMTU2/N2ZkNDA4MmZjZTM4/YTI3MTllMS93d3cu/Y2JzbmV3cy5jb20v"
hash: abe8a6b430fcb31a
embed_ref: cbsnews.com-FfH
app_id: images
skill_id: search`,
      parent_embed_id: "36ad23c6-4f10-4122-9261-006a40deafc1",
      embed_ids: null,
    },
    {
      embed_id: "43302f81-e421-43b3-80c3-0bedb85e4220",
      type: "image_result",
      content: `type: image_result
title: "The official Artemis II mission crew insignia is projected on the exterior of the Vehicle Assembly Building at NASA’s Kennedy Space Center in Florida on Friday, April 4, 2025. The patch designates the mission as “AII,” signifying not only the second major flight of the Artemis campaign, but also an endeavor of discovery that seeks to explore for all and by all. Framed in Apollo 8’s famous Earthrise photo, the scene of the Earth and the Moon represents the dual nature of human spaceflight"
source_page_url: "https://www.kennedyspacecenter.com/landing-pages/artemis-ii/"
image_url: "https://res.cloudinary.com/kennedy-space-center/image/upload/c_fill,h_1284,w_2140/q_auto/f_auto/IMAGEGALLERY_NASAKENNEDY_VAB_ArtemisIIPatch?_a=DATAdtXwZAA0"
thumbnail_url: "https://imgs.search.brave.com/F7osXj9eOE1pHUUVeUuaNStovfGzxpDrD-QlmYJ8OeI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9yZXMu/Y2xvdWRpbmFyeS5j/b20va2VubmVkeS1z/cGFjZS1jZW50ZXIv/aW1hZ2UvdXBsb2Fk/L2NfZmlsbCxoXzEy/ODQsd18yMTQwL3Ff/YXV0by9mX2F1dG8v/SU1BR0VHQUxMRVJZ/X05BU0FLRU5ORURZ/X1ZBQl9BcnRlbWlz/SUlQYXRjaD9fYT1E/QVRBZHRYd1pBQTA"
source: kennedyspacecenter.com
favicon_url: "https://imgs.search.brave.com/bhgDMEtHlEvRbzKe_JoA1lqHt8d5-riiqYzKC1pMt_4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvM2RkYjM2M2Nl/Mjc4MTAwY2YxZGVj/MWEyYjkxOWQyMTNm/NzM4ZGM5NTc0MTgz/YjVlZGU3YWNjYWY3/YWFlZWQ4MS93d3cu/a2VubmVkeXNwYWNl/Y2VudGVyLmNvbS8"
hash: 56ffd964a07a1138
embed_ref: kennedyspacecenter.com-luR
app_id: images
skill_id: search`,
      parent_embed_id: "7b320fe9-2c21-4aff-92a7-0b3100a7419b",
      embed_ids: null,
    },
    {
      embed_id: "9d9a1285-0a93-4f8c-b437-dd8c98bc02ef",
      type: "image_result",
      content: `type: image_result
title: The Artemis II mission crew in the Orion spacecraft
source_page_url: "https://www.bbc.com/news/articles/ce8jzr423p9o"
image_url: "https://ichef.bbci.co.uk/news/480/cpsprodpb/ca4a/live/ae932730-3430-11f1-a207-8b959fccb503.jpg.webp"
thumbnail_url: "https://imgs.search.brave.com/cMID9fZoKueMH5yWJxdax5gWSAKxcqwCz9_AuxbK8DI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pY2hl/Zi5iYmNpLmNvLnVr/L25ld3MvNDgwL2Nw/c3Byb2RwYi9jYTRh/L2xpdmUvYWU5MzI3/MzAtMzQzMC0xMWYx/LWEyMDctOGI5NTlm/Y2NiNTAzLmpwZy53/ZWJw"
source: bbc.com
favicon_url: "https://imgs.search.brave.com/-9uoAONEhH31ac708C2NinDM9OjKbNcruJo3O1baQTM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTljMGQ4ZTFj/YzcwNTIyYTU4ZDk4/ZTg5NTQ0NGQyYjQy/NzU3NTMxNDRjZGFi/NjFkMmRiNGE1MGE5/ZDhhOWMyZS93d3cu/YmJjLmNvbS8"
hash: 5d0e7d47b5ba5ab0
embed_ref: bbc.com-X2E
app_id: images
skill_id: search`,
      parent_embed_id: "7b320fe9-2c21-4aff-92a7-0b3100a7419b",
      embed_ids: null,
    },
    {
      embed_id: "39875cee-bfa5-41b5-8676-82e4bd7713d3",
      type: "image_result",
      content: `type: image_result
title: Artemis II crew closes in on Earth as mission ends with Pacific splashdown and more top headlines
source_page_url: "https://www.foxnews.com/us/artemis-ii-crew-reflects-emotionally-mission-after-safe-return-bonded-forever"
image_url: "https://a57.foxnews.com/static.foxnews.com/foxnews.com/content/uploads/2026/04/320/180/nasa-artemis-ii-astronauts-moon-mission.jpg?ve=1&tl=1"
thumbnail_url: "https://imgs.search.brave.com/nsQcmex4p9P0-0QEjnLkMUm8zCt0e00iTOWZYTj-74U/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9hNTcu/Zm94bmV3cy5jb20v/c3RhdGljLmZveG5l/d3MuY29tL2ZveG5l/d3MuY29tL2NvbnRl/bnQvdXBsb2Fkcy8y/MDI2LzA0LzMyMC8x/ODAvbmFzYS1hcnRl/bWlzLWlpLWFzdHJv/bmF1dHMtbW9vbi1t/aXNzaW9uLmpwZz92/ZT0xJnRsPTE"
source: foxnews.com
favicon_url: "https://imgs.search.brave.com/8Y6YYaSHf4PweCQwcB2IRvUWPCEsdNoek5FtyWqRRW4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGIyN2Q2NTE4/NGRmOTVmZGNmMzEy/OWJjY2MwNzkzYzg0/YWNhOGFmY2UxYTQ1/NmZiM2JkYzcxMjFh/MDFmNDBkYy93d3cu/Zm94bmV3cy5jb20v"
hash: dfd8139f631acb93
embed_ref: foxnews.com-Hnu
app_id: images
skill_id: search`,
      parent_embed_id: "7b320fe9-2c21-4aff-92a7-0b3100a7419b",
      embed_ids: null,
    },
    {
      embed_id: "eb18dbb1-49cc-4be2-b46b-4ea7b1512a78",
      type: "image_result",
      content: `type: image_result
title: r/space - Mission Specialist 1 Christina Koch
source_page_url: "https://reddit.com/r/space/comments/12godxq/nasas_artemis_ii_mission_crew_portraits"
image_url: "https://preview.redd.it/nasas-artemis-ii-mission-crew-portraits-v0-g7hpd7ndzvsa1.jpg?width=640&crop=smart&auto=webp&s=043a73790b8fa4ced6e0d80a31fcaf7d6726ae80"
thumbnail_url: "https://imgs.search.brave.com/_t8cPb6u_zxaTdADy61_HS9z94igJhLtw6Uq_YykIv0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9wcmV2/aWV3LnJlZGQuaXQv/bmFzYXMtYXJ0ZW1p/cy1paS1taXNzaW9u/LWNyZXctcG9ydHJh/aXRzLXYwLWc3aHBk/N25kenZzYTEuanBn/P3dpZHRoPTY0MCZj/cm9wPXNtYXJ0JmF1/dG89d2VicCZzPTA0/M2E3Mzc5MGI4ZmE0/Y2VkNmUwZDgwYTMx/ZmNhZjdkNjcyNmFl/ODA"
source: reddit.com
favicon_url: "https://imgs.search.brave.com/DiurNUpQ5h2-rFXH9KlBTV1zV9w6-RtG9hXKYTZC59g/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYzhlM2VlYjdj/YTI5NGExYWNkZWQ1/MWVjNjMyMjQzZTE5/YmYxOTdiZjQ3YjRj/NzAxMjBhNGZkMmYw/NTE1OGY2YS9yZWRk/aXQuY29tLw"
hash: 1bcb78754c0398d2
embed_ref: reddit.com-00z
app_id: images
skill_id: search`,
      parent_embed_id: "7b320fe9-2c21-4aff-92a7-0b3100a7419b",
      embed_ids: null,
    },
    {
      embed_id: "980c0c29-799b-4a89-934e-e8059f76a508",
      type: "image_result",
      content: `type: image_result
title: "The Artemis II crew is en route to the Moon on the second flight day of the mission. This photo shows the Orion spacecraft with the Moon in the distance, as captured by a camera on the tip of one of its solar array wings."
source_page_url: "https://www.space.com/news/live/artemis-2-nasa-moon-mission-updates-april-10-2026"
image_url: "https://cdn.mos.cms.futurecdn.net/3YJLTfj7wwSbJ4qMTLijxn.jpg"
thumbnail_url: "https://imgs.search.brave.com/tnXZ4O3qLIlp1pgefB3CteJ5xd7vDkzAsnD7gZkEUCM/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0LzNZ/SkxUZmo3d3dTYko0/cU1UTGlqeG4uanBn"
source: space.com
favicon_url: "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
hash: 3ca2e2b5e0122daf
embed_ref: space.com-idA
app_id: images
skill_id: search`,
      parent_embed_id: "7b320fe9-2c21-4aff-92a7-0b3100a7419b",
      embed_ids: null,
    },
    {
      embed_id: "7b320fe9-2c21-4aff-92a7-0b3100a7419b",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 9d9a1285-0a93-4f8c-b437-dd8c98bc02ef|39875cee-bfa5-41b5-8676-82e4bd7713d3|eb18dbb1-49cc-4be2-b46b-4ea7b1512a78|43302f81-e421-43b3-80c3-0bedb85e4220|980c0c29-799b-4a89-934e-e8059f76a508|f4d15606-a55e-4bec-8f30-893755dbc106
status: finished
query: Artemis II mission crew photos
id: 1
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["9d9a1285-0a93-4f8c-b437-dd8c98bc02ef", "39875cee-bfa5-41b5-8676-82e4bd7713d3", "eb18dbb1-49cc-4be2-b46b-4ea7b1512a78", "43302f81-e421-43b3-80c3-0bedb85e4220", "980c0c29-799b-4a89-934e-e8059f76a508", "f4d15606-a55e-4bec-8f30-893755dbc106"],
    },
    {
      embed_id: "f4d15606-a55e-4bec-8f30-893755dbc106",
      type: "image_result",
      content: `type: image_result
title: La NASA anuncia la cobertura de la misión lunar Artemis II
source_page_url: "https://www.nasa.gov/feature/our-artemis-crew/"
image_url: "https://www.nasa.gov/wp-content/uploads/2026/03/a2crew-7ff19d.jpg?w=1024"
thumbnail_url: "https://imgs.search.brave.com/WES451GWKJLHrtNmaaMh6ckXZP1NGNmsE1UpLgKHAlk/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMjYvMDMv/YTJjcmV3LTdmZjE5/ZC5qcGc_dz0xMDI0"
source: nasa.gov
favicon_url: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
hash: eb0d8b00946f7d35
embed_ref: nasa.gov-k1v
app_id: images
skill_id: search`,
      parent_embed_id: "7b320fe9-2c21-4aff-92a7-0b3100a7419b",
      embed_ids: null,
    },
    {
      embed_id: "0e706894-f0cb-4786-8156-9304d4285258",
      type: "image_result",
      content: `type: image_result
title: The Artemis II SLS rocket and Orion spacecraft at the launch pad under a blue sky.
source_page_url: "https://www.nasa.gov/blogs/missions/2026/02/21/nasa-troubleshooting-artemis-ii-rocket-upper-stage-issue-preparing-to-roll-back/"
image_url: "https://images-assets.nasa.gov/image/KSC-20260210-PH-JBS01-0126/KSC-20260210-PH-JBS01-0126~large.jpg?w=1920&h=1080&fit=clip&crop=faces,focalpoint"
thumbnail_url: "https://imgs.search.brave.com/FInyNMpH_Ubd-4RGw-QCkVsKS3CBRZc0coS4J97DxJ4/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMtYXNzZXRzLm5h/c2EuZ292L2ltYWdl/L0tTQy0yMDI2MDIx/MC1QSC1KQlMwMS0w/MTI2L0tTQy0yMDI2/MDIxMC1QSC1KQlMw/MS0wMTI2fmxhcmdl/LmpwZz93PTE5MjAm/aD0xMDgwJmZpdD1j/bGlwJmNyb3A9ZmFj/ZXMsZm9jYWxwb2lu/dA"
source: nasa.gov
favicon_url: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
hash: 7f99ccd1c45392c7
embed_ref: nasa.gov-6rZ
app_id: images
skill_id: search`,
      parent_embed_id: "0fccdcb0-7d81-4c34-b40c-b09923fa946d",
      embed_ids: null,
    },
    {
      embed_id: "70d86eeb-37fb-4c3d-937b-a39e28b70c1a",
      type: "image_result",
      content: `type: image_result
title: "NASA’s Space Launch System (SLS) rocket and Orion spacecraft, standing atop the mobile launcher, arrive at Launch Pad 39B at the agency’s Kennedy Space Center in Florida on Nov. 4, 2022, ahead of the uncrewed Artemis I launch."
source_page_url: "https://www.kennedyspacecenter.com/landing-pages/artemis-ii/"
image_url: "https://res.cloudinary.com/kennedy-space-center/image/upload/c_fill,h_1284,w_2140/q_auto/f_auto/IMAGEGALLERY_ArtemisI_LC39B?_a=DATAdtXwZAA0"
thumbnail_url: "https://imgs.search.brave.com/jzOBjuIvqTAhQhKM-sJEtL_qclFhMKuwXTKkcpWQ_M4/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9yZXMu/Y2xvdWRpbmFyeS5j/b20va2VubmVkeS1z/cGFjZS1jZW50ZXIv/aW1hZ2UvdXBsb2Fk/L2NfZmlsbCxoXzEy/ODQsd18yMTQwL3Ff/YXV0by9mX2F1dG8v/SU1BR0VHQUxMRVJZ/X0FydGVtaXNJX0xD/MzlCP19hPURBVEFk/dFh3WkFBMA"
source: kennedyspacecenter.com
favicon_url: "https://imgs.search.brave.com/bhgDMEtHlEvRbzKe_JoA1lqHt8d5-riiqYzKC1pMt_4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvM2RkYjM2M2Nl/Mjc4MTAwY2YxZGVj/MWEyYjkxOWQyMTNm/NzM4ZGM5NTc0MTgz/YjVlZGU3YWNjYWY3/YWFlZWQ4MS93d3cu/a2VubmVkeXNwYWNl/Y2VudGVyLmNvbS8"
hash: 36df6106b3a2b913
embed_ref: kennedyspacecenter.com-Xxu
app_id: images
skill_id: search`,
      parent_embed_id: "0fccdcb0-7d81-4c34-b40c-b09923fa946d",
      embed_ids: null,
    },
    {
      embed_id: "821c86cd-4aa5-4c1e-9940-cc173cfbc246",
      type: "image_result",
      content: `type: image_result
title: "NASA’s Space Launch System (SLS) rocket and Orion spacecraft, standing atop the mobile launcher, arrive at Launch Pad 39B at the agency’s Kennedy Space Center in Florida on Nov. 4, 2022, ahead of the uncrewed Artemis I launch."
source_page_url: "https://www.kennedyspacecenter.com/landing-pages/artemis-ii/"
image_url: "https://res.cloudinary.com/kennedy-space-center/image/upload/ar_5:3,c_fill,g_auto,w_500/q_auto/f_auto/FWIMAGE_ArtemisI_LC39B?_a=DATAdtXwZAA0"
thumbnail_url: "https://imgs.search.brave.com/Pa6yMvk_Bpu1JcDlMacN8wBtPqmdMYRntG0eouA3F7o/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9yZXMu/Y2xvdWRpbmFyeS5j/b20va2VubmVkeS1z/cGFjZS1jZW50ZXIv/aW1hZ2UvdXBsb2Fk/L2FyXzU6MyxjX2Zp/bGwsZ19hdXRvLHdf/NTAwL3FfYXV0by9m/X2F1dG8vRldJTUFH/RV9BcnRlbWlzSV9M/QzM5Qj9fYT1EQVRB/ZHRYd1pBQTA"
source: kennedyspacecenter.com
favicon_url: "https://imgs.search.brave.com/bhgDMEtHlEvRbzKe_JoA1lqHt8d5-riiqYzKC1pMt_4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvM2RkYjM2M2Nl/Mjc4MTAwY2YxZGVj/MWEyYjkxOWQyMTNm/NzM4ZGM5NTc0MTgz/YjVlZGU3YWNjYWY3/YWFlZWQ4MS93d3cu/a2VubmVkeXNwYWNl/Y2VudGVyLmNvbS8"
hash: 9e4492405a061503
embed_ref: kennedyspacecenter.com-FPL
app_id: images
skill_id: search`,
      parent_embed_id: "0fccdcb0-7d81-4c34-b40c-b09923fa946d",
      embed_ids: null,
    },
    {
      embed_id: "a192fc33-dedb-407f-bce6-cbfa0e897f5e",
      type: "image_result",
      content: `type: image_result
title: The Artemis II Space Launch System Rocket topped with the Orion spacecraft rolling out of the Vehicle Assembly Building at NASA’s Kennedy Space Center in Florida.
source_page_url: "https://www.boeing.com/space/space-launch-system"
image_url: "https://www.boeing.com/content/theboeingcompany/us/en/space/space-launch-system/_jcr_content/root/container/section_263884157/tabs/item_1/accordion/item_1770135091843/layout_container_cop/layout_column_1333176776/image.coreimg.jpeg/1770137367225/sls-accordion-1-4-rollout-01-26.jpeg"
thumbnail_url: "https://imgs.search.brave.com/MtaFGsIxHl-zk6MB64wTfw6UFAxVwrtsY7y6RlKwyRY/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/Ym9laW5nLmNvbS9j/b250ZW50L3RoZWJv/ZWluZ2NvbXBhbnkv/dXMvZW4vc3BhY2Uv/c3BhY2UtbGF1bmNo/LXN5c3RlbS9famNy/X2NvbnRlbnQvcm9v/dC9jb250YWluZXIv/c2VjdGlvbl8yNjM4/ODQxNTcvdGFicy9p/dGVtXzEvYWNjb3Jk/aW9uL2l0ZW1fMTc3/MDEzNTA5MTg0My9s/YXlvdXRfY29udGFp/bmVyX2NvcC9sYXlv/dXRfY29sdW1uXzEz/MzMxNzY3NzYvaW1h/Z2UuY29yZWltZy5q/cGVnLzE3NzAxMzcz/NjcyMjUvc2xzLWFj/Y29yZGlvbi0xLTQt/cm9sbG91dC0wMS0y/Ni5qcGVn"
source: boeing.com
favicon_url: "https://imgs.search.brave.com/xzDP_bMYe1Rhx9SCaGuBFXs9pJVUyCBHpnrzyHVIYIg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZmYwMThhMjRk/NDBlMmVjOWViZjk5/YTI1OTBjOWU0MzRh/ZDlkMGEyMmJkNWE0/YmM5MjUwYzVmMmJj/OTEyZjcxMS93d3cu/Ym9laW5nLmNvbS8"
hash: da73d9be5db58072
embed_ref: boeing.com-BSK
app_id: images
skill_id: search`,
      parent_embed_id: "0fccdcb0-7d81-4c34-b40c-b09923fa946d",
      embed_ids: null,
    },
    {
      embed_id: "0fccdcb0-7d81-4c34-b40c-b09923fa946d",
      type: "app_skill_use",
      content: `app_id: images
skill_id: search
result_count: 6
embed_ids: 0e706894-f0cb-4786-8156-9304d4285258|70d86eeb-37fb-4c3d-937b-a39e28b70c1a|821c86cd-4aa5-4c1e-9940-cc173cfbc246|a192fc33-dedb-407f-bce6-cbfa0e897f5e|42ddd69b-c276-4a65-9eea-09459585fbc8|1e398ce5-54ac-4096-b210-e05d7efbb770
status: finished
query: Artemis II Orion spacecraft and SLS rocket photos
id: 2
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["0e706894-f0cb-4786-8156-9304d4285258", "70d86eeb-37fb-4c3d-937b-a39e28b70c1a", "821c86cd-4aa5-4c1e-9940-cc173cfbc246", "a192fc33-dedb-407f-bce6-cbfa0e897f5e", "42ddd69b-c276-4a65-9eea-09459585fbc8", "1e398ce5-54ac-4096-b210-e05d7efbb770"],
    },
    {
      embed_id: "42ddd69b-c276-4a65-9eea-09459585fbc8",
      type: "image_result",
      content: `type: image_result
title: "NASA’s Space Launch System (SLS) rocket with the Orion spacecraft aboard is seen atop the mobile launcher at Launch 39B at NASA’s Kennedy Space Center in Florida. Artemis I mission is the first integrated test of the agency’s deep space exploration systems: the Space Launch System rocket, Orion spacecraft, and supporting ground systems. The mission is the first in a series of increasingly complex missions to the Moon. Launch of the uncrewed flight test is targeted for no earlier than Sept."
source_page_url: "https://www.nasa.gov/mission/artemis-i/"
image_url: "https://images-assets.nasa.gov/image/MAF_20220830__KSC_Artemis1_epb_008/MAF_20220830__KSC_Artemis1_epb_008~large.jpg?w=1280&h=1920&fit=clip&crop=faces,focalpoint"
thumbnail_url: "https://imgs.search.brave.com/w12SHHMPlh3QduhAk6gx142ReD3qiVFbZzKagHaWhso/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMtYXNzZXRzLm5h/c2EuZ292L2ltYWdl/L01BRl8yMDIyMDgz/MF9fS1NDX0FydGVt/aXMxX2VwYl8wMDgv/TUFGXzIwMjIwODMw/X19LU0NfQXJ0ZW1p/czFfZXBiXzAwOH5s/YXJnZS5qcGc_dz0x/MjgwJmg9MTkyMCZm/aXQ9Y2xpcCZjcm9w/PWZhY2VzLGZvY2Fs/cG9pbnQ"
source: nasa.gov
favicon_url: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
hash: e08528a963e426bb
embed_ref: nasa.gov-RCb
app_id: images
skill_id: search`,
      parent_embed_id: "0fccdcb0-7d81-4c34-b40c-b09923fa946d",
      embed_ids: null,
    },
    {
      embed_id: "1e398ce5-54ac-4096-b210-e05d7efbb770",
      type: "image_result",
      content: `type: image_result
title: "NASA rolls out the SLS rocket  and Orion spacecraft for the Artemis 2 moon mission on Jan. 17, 2026."
source_page_url: "https://space.com/space-exploration/artemis/nasa-stacks-artemis-2-moon-missions-orion-capsule-atop-sls-rocket-ahead-of-2026-launch"
image_url: "https://cdn.mos.cms.futurecdn.net/YyjM33WKW7nZjhiGiozANN.jpg"
thumbnail_url: "https://imgs.search.brave.com/hN0E6Af2zPj4xT0DBPlrIZ_wah2TtXSQI4gj6xLSgd0/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L1l5/ak0zM1dLVzduWmpo/aUdpb3pBTk4uanBn"
source: space.com
favicon_url: "https://imgs.search.brave.com/ovWUdVFP58Ix_5hFz6UyyfUlyIBsreiliCzaAtHRHwA/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjk4MzAxZmU5/MGFkNDYxYzcwZWU3/NTIxMGMxZDJmMmJi/NGZkYjZlMDJhMzVi/M2ZhNjBjYWNkM2Y0/ZTA1MGNmNi9zcGFj/ZS5jb20v"
hash: b3bc3e8438654ae6
embed_ref: space.com-PKh
app_id: images
skill_id: search`,
      parent_embed_id: "0fccdcb0-7d81-4c34-b40c-b09923fa946d",
      embed_ids: null,
    },
    {
      embed_id: "3de6a73b-af1d-4803-961a-c001d7a8505b",
      type: "website",
      content: `type: search_result
title: "Artemis II: NASA’s First Crewed Lunar Flyby in 50 Years - NASA"
url: "https://www.nasa.gov/mission/artemis-ii/"
description: "The Artemis II mission will carry astronauts farther from Earth and closer to the Moon than any human has been in over half a century. From this unique vantage point and environment, the Artemis II crew will work with scientists on Earth to ..."
page_age: 1 day ago
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/XTe_6-RAicnjSqrXlPo2AkahT4V_JewCb4xk2yJht_I/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMtYXNzZXRzLm5h/c2EuZ292L2ltYWdl/L0tTQy0yMDIzMDky/MC1QSC1GTVgwMV8w/NDY3L0tTQy0yMDIz/MDkyMC1QSC1GTVgw/MV8wNDY3fmxhcmdl/LmpwZw"
thumbnail_original: "https://images-assets.nasa.gov/image/KSC-20230920-PH-FMX01_0467/KSC-20230920-PH-FMX01_0467~large.jpg"
extra_snippets: "The first crewed Artemis flight marks a key step toward long‑term return to the Moon and future missions to Mars. ... Meet the astronauts who ventured around the Moon on Artemis II, the first crewed flight aboard NASA’s human deep space capabilities, paving the way for future lunar surface missions.|Forging New Frontiers about Our Artemis II Crew ... Orion is developed to be capable of sending astronauts to the Moon and is a crucial step toward eventually sending crews on to Mars. The Orion spacecraft will serve as the exploration vehicle that will carry and sustain the crew on Artemis missions to the Moon and return them safely to Earth.|The Artemis II mission will carry astronauts farther from Earth and closer to the Moon than any human has been in over half a century. From this unique vantage point and environment, the Artemis II crew will work with scientists on Earth to facilitate science investigations to inform future human spaceflight missions.|A closeup view shows the Orion spacecraft and launch abort system for NASA’s Artemis II test flight at Launch Complex 39B at Kennedy Space Center in Florida on Tuesday, Feb. 10, 2026. ... Offering more payload mass, volume, and departure energy than any other single rocket, SLS (Space Launch System) can support a range of mission objectives."
hash: 68727ee4f529c04b
embed_ref: nasa.gov-Qtg
app_id: web
skill_id: search`,
      parent_embed_id: "df72165a-a89b-4aba-84fc-b4bc870d8457",
      embed_ids: null,
    },
    {
      embed_id: "9200a191-3376-49de-b9cd-797dbb5cbecf",
      type: "website",
      content: `type: search_result
title: Artemis II - Wikipedia
url: "https://en.wikipedia.org/wiki/Artemis_II"
description: Artemis II was the second flight ... mission was a test flight supporting subsequent Artemis missions aimed at returning humans to the lunar surface....
page_age: 4 hours ago
profile_name: Wikipedia
meta_url_favicon: "https://imgs.search.brave.com/m6XxME4ek8DGIUcEPCqjRoDjf2e54EwL9pQzyzogLYk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjQwNGZhZWY0/ZTQ1YWUzYzQ3MDUw/MmMzMGY3NTQ0ZjNj/NDUwMDk5ZTI3MWRk/NWYyNTM4N2UwOTE0/NTI3ZDQzNy9lbi53/aWtpcGVkaWEub3Jn/Lw"
thumbnail_src: "https://imgs.search.brave.com/9AIv_1HWqEWntsJ_4DtpkG44gQKUT2GlXYIp1jH4Nkk/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy8x/LzE1L0VhcnRoc2V0/XyUyOGFydDAwMmUw/MDkyODglMjkuanBn"
thumbnail_original: "https://upload.wikimedia.org/wikipedia/commons/1/15/Earthset_%28art002e009288%29.jpg"
extra_snippets: "Artemis II was a crewed nine-day lunar flyby mission that launched on April 1, 2026. With a crew of four astronauts, it was the first crewed flight of the NASA-led Artemis program and the first crewed flight beyond low Earth orbit since Apollo 17 in 1972. Artemis II was the second flight of ...|Artemis II was the second flight of the Space Launch System (SLS) and the first crewed flight of the Orion spacecraft, named Integrity by the crew. The mission was a test flight supporting subsequent Artemis missions aimed at returning humans to the lunar surface.|Originally designated Exploration Mission-2 (EM-2) and intended to support the canceled Asteroid Redirect Mission, its objectives were revised after the establishment of the Artemis program in 2017. Artemis II's mission objectives were similar to those of Apollo 8 in 1968, the first crewed lunar flight during the Apollo program, while its free-return trajectory resembled that flown by Apollo 13 in 1970.|NASA reported that temperatures inside the crew module remained within design limits, but the unanticipated behavior prompted further analysis. Close-up imagery of the damage was not publicly released until May 2024, when it appeared in a report issued by the NASA Office of Inspector General. In April 2024, NASA established an independent review team to assess the heat‑shield performance and the agency's proposed approach for the Artemis II mission.|As part of the certification process for Artemis II, NASA conducted additional testing and analysis, including evaluations of scenarios involving more extensive heat-shield damage. NASA stated that these analyses showed the underlying structure of the Orion capsule would remain intact and capable of protecting the crew under conditions exceeding those expected during the mission's reentry."
hash: 80253ed9b40ec362
embed_ref: en.wikipedia.org-3HB
app_id: web
skill_id: search`,
      parent_embed_id: "df72165a-a89b-4aba-84fc-b4bc870d8457",
      embed_ids: null,
    },
    {
      embed_id: "8ec0253d-1dac-413d-99a4-6eb3a69fee54",
      type: "website",
      content: `type: search_result
title: ESA - Artemis II
url: "https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/Orion/Artemis_II"
description: "At the heart of this historic mission is ESA’s European Service Module, which provides the Orion spacecraft and its crew with life support, power and propulsion, enabling safe human travel beyond Earth orbit. Orion and its European Service Module during Artemis I · Following the Artemis I uncrewed test flight, Artemis II will see a crew of four astronauts – NASA astronauts Reid Wiseman, Victor Glover and Christina Koch, and Canadian Space Agency astronaut Jeremy Hansen – complete a different flight path."
page_age: 6 hours ago
profile_name: ESA
meta_url_favicon: "https://imgs.search.brave.com/N7-ExSQiugqqIBRMMrGU-p51XsvjXMNwJ7679FEfN34/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNmQ1ZDJmNWJi/Y2FhNmQ0M2FlNzgy/YjQ3ZThmYmY3Yzk0/YzIxYmI0YjU2NWMy/ZjVjNzUwM2FjYWRi/OWM4NmM5OC93d3cu/ZXNhLmludC8"
thumbnail_src: "https://imgs.search.brave.com/xpnTrNa480U2unkgZvwZzKFaqs5N7oN1KSpKSSY2fMw/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/ZXNhLmludC92YXIv/ZXNhL3N0b3JhZ2Uv/aW1hZ2VzL2VzYV9t/dWx0aW1lZGlhL2lt/YWdlcy8yMDI0LzA1/L2Fwb2xsb190b19h/cnRlbWlzLzI2MDcz/NDUxLTEtZW5nLUdC/L0Fwb2xsb190b19B/cnRlbWlzX3BpbGxh/cnMuanBn"
thumbnail_original: "https://www.esa.int/var/esa/storage/images/esa_multimedia/images/2024/05/apollo_to_artemis/26073451-1-eng-GB/Apollo_to_Artemis_pillars.jpg"
extra_snippets: "Artemis II will be the first crewed mission of the Artemis programme, carrying four astronauts on a journey around the Moon and back to Earth for the first time in over half a century. At the heart of this historic mission is ESA’s European Service Module, which provides the Orion spacecraft and its crew with life support, power and propulsion, enabling safe human travel beyond Earth orbit.|At the heart of this historic mission is ESA’s European Service Module, which provides the Orion spacecraft and its crew with life support, power and propulsion, enabling safe human travel beyond Earth orbit. Orion and its European Service Module during Artemis I · Following the Artemis I uncrewed test flight, Artemis II will see a crew of four astronauts – NASA astronauts Reid Wiseman, Victor Glover and Christina Koch, and Canadian Space Agency astronaut Jeremy Hansen – complete a different flight path.|The second Artemis mission builds on the first, continuing to test the capabilities of the Orion spacecraft and its European Service Module, now fitted with life support systems to keep the crew safe and healthy.|After reaching Earth orbit, the rocket’s upper stage will boost Orion into a highly elliptical orbit, where the crew and mission teams will verify that all systems are performing as expected. During this phase, astronauts will also take manual control of the spacecraft to conduct a proximity operations demonstration with Orion using the European Service Module’s engines. These capabilities will play a critical role in future Artemis missions, particularly in delivering and positioning Gateway elements such as ESA’s Lunar I-Hab module."
hash: 3a974391cc465576
embed_ref: esa.int-5rg
app_id: web
skill_id: search`,
      parent_embed_id: "df72165a-a89b-4aba-84fc-b4bc870d8457",
      embed_ids: null,
    },
    {
      embed_id: "c106d3db-011e-407c-9ac5-c8aa4b773ca4",
      type: "website",
      content: `type: search_result
title: NASA Answers Your Most Pressing Artemis II Questions - NASA
url: "https://www.nasa.gov/missions/nasa-answers-your-most-pressing-artemis-ii-questions/"
description: The Artemis II test flight will confirm the systems necessary to support astronauts in deep space exploration and prepare to establish a sustained presence on the Moon. The primary goal of Artemis II is a crewed test flight in lunar space. There ...
page_age: 2 days ago
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/Y1wspe4GVToe_bL8V3um8H8BXRCaRDPAf5jOaJy-tkU/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMtYXNzZXRzLm5h/c2EuZ292L2ltYWdl/L2FydDAwMmUwMDg0/ODYvYXJ0MDAyZTAw/ODQ4Nn5sYXJnZS5q/cGc_dz0xOTIwJmFt/cDtoPTE0NDAmYW1w/O2ZpdD1jbGlwJmFt/cDtjcm9wPWZhY2Vz/JTJDZm9jYWxwb2lu/dA"
thumbnail_original: "https://images-assets.nasa.gov/image/art002e008486/art002e008486~large.jpg?w=1920&amp;h=1440&amp;fit=clip&amp;crop=faces%2Cfocalpoint"
extra_snippets: "Food flying aboard Artemis II is designed to support crew health and performance during the mission around the Moon. Menu selections are developed with space food experts and the crew to balance calorie needs, hydration, and nutrient intake while accommodating individual preferences. For more information about their menu, visit here. What are the goals of the Artemis II Mission?|The first crewed test flight under NASA’s Artemis program is underway. Four Artemis II astronauts are flying aboard NASA’s Orion spacecraft around the Moon|The Artemis II test flight will confirm the systems necessary to support astronauts in deep space exploration and prepare to establish a sustained presence on the Moon. The primary goal of Artemis II is a crewed test flight in lunar space. There are five main additional priorities for Artemis II:|NASA astronaut Christina Koch, Artemis II mission specialist, peers out of one of the Orion spacecraft’s main cabin windows on Saturday, April 4, 2026, looking back at Earth, as the crew travel toward the Moon."
hash: 1ac6d872aa4164fb
embed_ref: nasa.gov-nQe
app_id: web
skill_id: search`,
      parent_embed_id: "df72165a-a89b-4aba-84fc-b4bc870d8457",
      embed_ids: null,
    },
    {
      embed_id: "0ba5ed54-17c8-4e9e-b7d2-fd09bb688cf7",
      type: "website",
      content: `type: search_result
title: Our Artemis Crew - NASA
url: "https://www.nasa.gov/feature/our-artemis-crew/"
description: Artemis II will be NASA’s first ... to verify today’s capabilities for humans to explore deep space and pave the way for long-term exploration and science on the lunar surface....
page_age: "February 24, 2023"
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/wHTm9r71TH7SpN6JXYosETZUsPalSkzamRyU1EodrfA/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMjMvMDgv/YmV0dGVyLW9yaW9u/LW1lZGlhLWRheS0w/OC0wOC0yMy5qcGc"
thumbnail_original: "https://www.nasa.gov/wp-content/uploads/2023/08/better-orion-media-day-08-08-23.jpg"
extra_snippets: "Four astronauts have been selected for NASA’s Artemis II mission: Commander Reid Wiseman, pilot Victor Glover, and mission specialist Christina Koch from NASA, and mission specialist Jeremy Hansen from the Canadian Space Agency. Artemis II will be NASA’s first crewed flight test of the Space Launch System rocket and Orion spacecraft around the Moon to verify today’s capabilities for humans to explore deep space and pave the way for long-term exploration and science on the lunar surface.|Artemis II is NASA’s first mission with crew aboard our foundational deep space rocket, the SLS (Space Launch System), and Orion spacecraft and will confirm all the spacecraft’s systems operate as designed with crew aboard in the actual environment of deep space.|The mission will pave the way for lunar surface missions, establishing long-term lunar science and exploration capabilities, and inspire the next generation of explorers. The Artemis II crew is shown inside the Neil Armstrong Operations and Checkout Building at NASA’s Kennedy Space Center in Florida in front of their Orion crew module on Aug.|Meet the astronauts who will venture around the Moon on Artemis II, the first crewed flight aboard NASA’s human deep space capabilities, paving the way for future lunar surface missions."
hash: f91e97af7f4dd58a
embed_ref: nasa.gov-mYc
app_id: web
skill_id: search`,
      parent_embed_id: "df72165a-a89b-4aba-84fc-b4bc870d8457",
      embed_ids: null,
    },
    {
      embed_id: "866cd690-3198-45d5-a23d-2223f74ab33d",
      type: "website",
      content: `type: search_result
title: What is Nasa's Artemis II Moon mission and what are the crew doing?
url: "https://www.bbc.com/news/articles/c0q4w3l0wdvo"
description: "The Artemis II astronauts are on the final leg of their journey home after conducting a historic lunar fly-by, which took them further from Earth than any humans have ever been. As planned, the four-person crew did not land on the Moon but their mission sets the stage for a future human landing for the first time since the 1960s and 70s."
page_age: 3 days ago
profile_name: BBC
meta_url_favicon: "https://imgs.search.brave.com/-9uoAONEhH31ac708C2NinDM9OjKbNcruJo3O1baQTM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTljMGQ4ZTFj/YzcwNTIyYTU4ZDk4/ZTg5NTQ0NGQyYjQy/NzU3NTMxNDRjZGFi/NjFkMmRiNGE1MGE5/ZDhhOWMyZS93d3cu/YmJjLmNvbS8"
thumbnail_src: "https://imgs.search.brave.com/FrvGDsPNQxreE3UDUYw49cT5KAm7Zp2asTtsRGUmX68/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pY2hl/Zi5iYmNpLmNvLnVr/L25ld3MvMTAyNC9i/cmFuZGVkX25ld3Mv/NTBkYy9saXZlLzhl/YmZiMzAwLTJkMWYt/MTFmMS1iMjk3LTk1/YjBhMGE4MzMxZS5q/cGc"
thumbnail_original: "https://ichef.bbci.co.uk/news/1024/branded_news/50dc/live/8ebfb300-2d1f-11f1-b297-95b0a0a8331e.jpg"
extra_snippets: "The Artemis II astronauts are on the final leg of their journey home after conducting a historic lunar fly-by, which took them further from Earth than any humans have ever been. As planned, the four-person crew did not land on the Moon but their mission sets the stage for a future human landing for the first time since the 1960s and 70s.|Watch the moment Artemis II blasts into space on historic mission · The Orion space capsule is crewed by four astronauts: Americans Reid Wiseman, Victor Glover, Christina Koch and Canadian Jeremy Hansen.|Astronauts shared their pre-launch messages from inside the Orion crew capsule during the 10-minute countdown to lift off. \\"We are going for all humanity,\\" said mission specialist Hansen. Cheers erupted among jubilant crowds gathered outside the Kennedy Space Center, as Nasa technicians monitored the ascent. Observers also watched as various milestones were achieved, like seeing the twin rocket boosters separate from the rocket after helping it reach a speed of more than 10,000mph (16,100km/h) Once Artemis II entered the upper atmosphere, Orion commander Wiseman declared it was a \\"great view\\".|Ahead of that, Nasa plans another crewed test mission, Artemis III, in 2027, to rehearse Orion's rendezvous and docking with one or more lunar landers and to try out the new spacesuits if they are ready in time."
hash: 31c71648eec3e549
embed_ref: bbc.com-cY9
app_id: web
skill_id: search`,
      parent_embed_id: "df72165a-a89b-4aba-84fc-b4bc870d8457",
      embed_ids: null,
    },
    {
      embed_id: "df72165a-a89b-4aba-84fc-b4bc870d8457",
      type: "app_skill_use",
      content: `app_id: web
skill_id: search
result_count: 6
embed_ids: 3de6a73b-af1d-4803-961a-c001d7a8505b|9200a191-3376-49de-b9cd-797dbb5cbecf|8ec0253d-1dac-413d-99a4-6eb3a69fee54|c106d3db-011e-407c-9ac5-c8aa4b773ca4|0ba5ed54-17c8-4e9e-b7d2-fd09bb688cf7|866cd690-3198-45d5-a23d-2223f74ab33d
status: finished
query: Artemis II crew and mission goals
id: 2
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["3de6a73b-af1d-4803-961a-c001d7a8505b", "9200a191-3376-49de-b9cd-797dbb5cbecf", "8ec0253d-1dac-413d-99a4-6eb3a69fee54", "c106d3db-011e-407c-9ac5-c8aa4b773ca4", "0ba5ed54-17c8-4e9e-b7d2-fd09bb688cf7", "866cd690-3198-45d5-a23d-2223f74ab33d"],
    },
    {
      embed_id: "fa3654bf-3653-436c-9077-2a2f41816f0c",
      type: "app_skill_use",
      content: `app_id: web
skill_id: search
result_count: 6
embed_ids: b4d111da-0349-47ad-8b94-23001f8e4375|b5a438b1-a8d4-4de4-bf51-2c982c0caf72|82f50f48-053d-469d-8dbf-2b3f770cb204|7d12fc4c-06e2-4d41-949f-6441b9ae4bac|41e097c3-4d13-444b-80d7-41d3a08f47cf|f9f92654-cbbd-44e2-a744-291dfcb501ac
status: finished
query: Artemis II mission status and details April 2026
id: 1
provider: Brave Search`,
      parent_embed_id: null,
      embed_ids: ["b4d111da-0349-47ad-8b94-23001f8e4375", "b5a438b1-a8d4-4de4-bf51-2c982c0caf72", "82f50f48-053d-469d-8dbf-2b3f770cb204", "7d12fc4c-06e2-4d41-949f-6441b9ae4bac", "41e097c3-4d13-444b-80d7-41d3a08f47cf", "f9f92654-cbbd-44e2-a744-291dfcb501ac"],
    },
    {
      embed_id: "f9f92654-cbbd-44e2-a744-291dfcb501ac",
      type: "website",
      content: `type: search_result
title: NASA’s Artemis II Crew Comes Home (Official Broadcast) | NASA+
url: "https://plus.nasa.gov/scheduled-video/nasas-artemis-ii-crew-comes-home-official-broadcast/"
description: "Around the Moon and back. Watch the Artemis II astronauts come home. NASA’s Artemis II mission is splashing down in the Pacific Ocean at about 8:07 p.m. EDT on Friday, April 10."
page_age: 1 day ago
profile_name: NASA +
meta_url_favicon: "https://imgs.search.brave.com/Yfk_9jQJ5wXHVA6jmPYcioJpZZ7QBbIuYcxB6oLuJRU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMDM4NjliZDRl/MjBjZGJiNDE1NWI1/ZTE4MDZlNmNhN2Q1/Njc1NTc2ZWI1NjM1/YjAxMjlmNjgxOWUy/Y2VjYjFiYy9wbHVz/Lm5hc2EuZ292Lw"
thumbnail_src: "https://imgs.search.brave.com/UGQLF1SH4dJIr9VXgsCZt7wc0JiL-4gJf7Q7lNKv9mM/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9wbHVz/Lm5hc2EuZ292L3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDI2LzA0/L2FydGVtaXMtaWkt/cmVlbnRyeS1hbmQt/c3BsYXNoZG93bi1y/MS1ob3Jpem9udGFs/LXByb2dyYW0tdGls/ZS0xNi05LXdpdGhv/dXQtdGl0bGUuanBn"
thumbnail_original: "https://plus.nasa.gov/wp-content/uploads/2026/04/artemis-ii-reentry-and-splashdown-r1-horizontal-program-tile-16-9-without-title.jpg"
extra_snippets: "April 10, 2026 6:30 pm · Around the Moon and back. Watch the Artemis II astronauts come home. NASA’s Artemis II mission is splashing down in the Pacific Ocean at about 8:07 p.m. EDT on Friday, […] 00 · Days · 00 · Hours · 00 · Min · 00 · Sec · This event has already occurred Open Video Player ·|April 10, 2026 6:30 pm · Watch Livestream · Facebook · Pinterest · Reddit · X · LinkedIn · Telegram · Email · WhatsApp · https://plus.nasa.gov/scheduled-video/nasas-artemis-ii-crew-comes-home-official-broadcast/Copy URL to clipboard> Share · Google Calendar · ICS File Add to Calendar · Around the Moon and back. Watch the Artemis II astronauts come home. NASA’s Artemis II mission is splashing down in the Pacific Ocean at about 8:07 p.m.|Around the Moon and back. Watch the Artemis II astronauts come home. NASA’s Artemis II mission is splashing down in the Pacific Ocean at about 8:07 p.m. EDT on Friday, April 10."
hash: d7c848a2ec802c01
embed_ref: plus.nasa.gov-Srx
app_id: web
skill_id: search`,
      parent_embed_id: "fa3654bf-3653-436c-9077-2a2f41816f0c",
      embed_ids: null,
    },
    {
      embed_id: "41e097c3-4d13-444b-80d7-41d3a08f47cf",
      type: "website",
      content: `type: search_result
title: "Artemis II Flight Day 6: Lunar Flyby Updates - NASA"
url: "https://www.nasa.gov/blogs/missions/2026/04/06/artemis-ii-flight-day-6-lunar-flyby-updates/"
description: "The Artemis II crew has completed ... the return trip home. On Tuesday, April 7, Orion will exit the lunar sphere of influence at approximately 1:25 p.m., at a distance of 41,072 miles from the Moon...."
page_age: 5 days ago
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/1A4HdnVEIL3D75dwygDuQWxLlZX2lAY206TIaWtI5q0/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMjYvMDQv/YXJ0MDAyZTAwOTIx/Mm9yaWcuanBn"
thumbnail_original: "https://www.nasa.gov/wp-content/uploads/2026/04/art002e009212orig.jpg"
extra_snippets: "The Artemis II crew has completed the mission’s lunar observation period and is now beginning the return trip home. On Tuesday, April 7, Orion will exit the lunar sphere of influence at approximately 1:25 p.m., at a distance of 41,072 miles from the Moon.|The Artemis II crew of NASA astronauts Reid Wiseman, Victor Glover, and Christina Koch, along with CSA (Canadian Space Agency) astronaut Jeremy Hansen have set the record for the farthest distance from Earth traveled by a human mission, surpassing the Apollo 13 record of 248,655 miles set in 1970.|Live lunar flyby updates for NASA’s Artemis II mission will be published on this page.|The Artemis II crew has reached the mission’s maximum distance from Earth at 252,756 miles, setting a new record for human spaceflight."
hash: 485b9fa9f16a46fd
embed_ref: nasa.gov-haz
app_id: web
skill_id: search`,
      parent_embed_id: "fa3654bf-3653-436c-9077-2a2f41816f0c",
      embed_ids: null,
    },
    {
      embed_id: "b4d111da-0349-47ad-8b94-23001f8e4375",
      type: "website",
      content: `type: search_result
title: "Artemis II Flight Day 9: Crew Prepares to Come Home - NASA"
url: "https://www.nasa.gov/blogs/missions/2026/04/09/artemis-ii-flight-day-9-crew-prepares-to-come-home/"
description: "... Editor’s Note: This blog ... milestones. On their last full day in space, the Artemis II crew began the morning with “Lonesome Drifter” by Charley Crockett as they approached Earth at 147,337 miles...."
page_age: 2 days ago
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/hPuEBS3QPONeIIWDOC8yf0OB2fzsgCgleSWLx5j3Dlc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMjYvMDQv/NTUxOTM3NzI1NTIt/YjhjZmI0N2I3ZS1v/LmpwZw"
thumbnail_original: "https://www.nasa.gov/wp-content/uploads/2026/04/55193772552-b8cfb47b7e-o.jpg"
extra_snippets: "The crew was selected in April 2023, and have been training together for their mission for the past three years. ... Editor’s Note: This blog was updated on April 9, 2026, to update the times for key splashdown milestones. On their last full day in space, the Artemis II crew began the morning with “Lonesome Drifter” by Charley Crockett as they approached Earth at 147,337 miles.|Infographic featuring the Artemis II Orion lofted entry sequence. This graphic was presented by Artemis II Flight Director Rick Henfling during the mission status briefing to the media and public on April 8, 2026 at NASA’s Johnson Space Center in Houston.|Infographic displaying the Artemis II Orion parachute sequence. This graphic was presented by Artemis II Flight Director Rick Henfling during the mission status briefing to the media and public on April 8, 2026 at NASA’s Johnson Space Center in Houston.|Ground track map displaying the Artemis II Orion parachute sequence. This graphic was presented by Artemis II Flight Director Rick Henfling during the mission status briefing to the media and public on April 8, 2026 at NASA’s Johnson Space Center in Houston."
hash: bca4646d73978378
embed_ref: nasa.gov-7Bg
app_id: web
skill_id: search`,
      parent_embed_id: "fa3654bf-3653-436c-9077-2a2f41816f0c",
      embed_ids: null,
    },
    {
      embed_id: "7d12fc4c-06e2-4d41-949f-6441b9ae4bac",
      type: "website",
      content: `type: search_result
title: Artemis II Launch Day Updates - NASA
url: "https://www.nasa.gov/blogs/missions/2026/04/01/live-artemis-ii-launch-day-updates/"
description: "Main engine cutoff of the SLS (Space Launch System) core stage is complete, and the core stage has successfully separated from the interim cryogenic propulsion stage and the Orion spacecraft."
page_age: 1 week ago
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/38hslOJ277Z41-5yAui27ehimQBm-nndTciW8Lni5pU/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMjYvMDQv/NTUxODI4Nzg0MDkt/ZDZjNDZhNzNhMC1r/LmpwZw"
thumbnail_original: "https://www.nasa.gov/wp-content/uploads/2026/04/55182878409-d6c46a73a0-k.jpg"
extra_snippets: "NASA’s Artemis II SLS (Space Launch System) rocket and Orion spacecraft lift off from Launch Complex 39B at NASA’s Kennedy Space Center in Florida on Wednesday, April 1, 2026. The Artemis II test flight will take NASA astronauts Commander Reid Wiseman, Pilot Victor Glover, and Mission Specialist Christina Koch, and CSA (Canadian Space Agency) astronaut Mission Specialist Jeremy Hansen, on an approximately 10-day mission around the Moon and back to Earth.|Main engine cutoff of the SLS (Space Launch System) core stage is complete, and the core stage has successfully separated from the interim cryogenic propulsion stage and the Orion spacecraft. This marks the end of the first major propulsion phase of the Artemis II mission and the transition to upper‑stage operations.|SLS clears launch tower; roll/pitch maneuver (Mission Elapsed Time [MET]) +00:00:07) ... The Artemis II countdown has entered terminal count, and the ground launch sequencer has taken control, orchestrating a precise series of automated commands to prepare the SLS (Space Launch System) rocket and Orion spacecraft for liftoff at a T-0 time of 6:35 p.m.|This automated sequence minimizes human intervention, reducing risk and ensuring synchronization across complex subsystems. For Artemis II, this moment marks the culmination of years of planning and testing, as the mission moves from ground operations to the threshold of launch."
hash: c099a94f1481fbf6
embed_ref: nasa.gov-mEC
app_id: web
skill_id: search`,
      parent_embed_id: "fa3654bf-3653-436c-9077-2a2f41816f0c",
      embed_ids: null,
    },
    {
      embed_id: "82f50f48-053d-469d-8dbf-2b3f770cb204",
      type: "website",
      content: `type: search_result
title: NASA Answers Your Most Pressing Artemis II Questions - NASA
url: "https://www.nasa.gov/missions/nasa-answers-your-most-pressing-artemis-ii-questions/"
description: "NASA’s Artemis II mission is scheduled to splash down off the coast of San Diego at approximately 8:07 p.m. EDT (5:07 p.m. PDT) on Friday, April 10. Following splashdown, recovery teams will retrieve the crew using helicopters and deliver ..."
page_age: 2 days ago
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/Y1wspe4GVToe_bL8V3um8H8BXRCaRDPAf5jOaJy-tkU/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMtYXNzZXRzLm5h/c2EuZ292L2ltYWdl/L2FydDAwMmUwMDg0/ODYvYXJ0MDAyZTAw/ODQ4Nn5sYXJnZS5q/cGc_dz0xOTIwJmFt/cDtoPTE0NDAmYW1w/O2ZpdD1jbGlwJmFt/cDtjcm9wPWZhY2Vz/JTJDZm9jYWxwb2lu/dA"
thumbnail_original: "https://images-assets.nasa.gov/image/art002e008486/art002e008486~large.jpg?w=1920&amp;h=1440&amp;fit=clip&amp;crop=faces%2Cfocalpoint"
extra_snippets: "NASA astronaut Christina Koch, Artemis II mission specialist, peers out of one of the Orion spacecraft’s main cabin windows on Saturday, April 4, 2026, looking back at Earth, as the crew travel toward the Moon.|Editor’s Note: This article was updated at 1:40 p.m. EDT on Sunday, April 5, 2026, to correct the time for the distance record, and adjust other times for lunar flyby activities. The first crewed test flight under NASA’s Artemis program is underway.|Daily mission status briefings are held live from the agency’s Johnson Space Center in Houston through splashdown, except for Monday, April 6, due to lunar flyby activities. A list of activities is regularly updated online. The crew are participating in live conversations throughout the mission, which were scheduled prior to their departure from Earth. NASA will provide the exact times of each of these downlink events, as well as the latest mission coverage, on the Artemis blog.|NASA’s Artemis II mission is scheduled to splash down off the coast of San Diego at approximately 8:07 p.m. EDT (5:07 p.m. PDT) on Friday, April 10. Following splashdown, recovery teams will retrieve the crew using helicopters and deliver them to the USS John P."
hash: 1ac6d872aa4164fb
embed_ref: nasa.gov-7Me
app_id: web
skill_id: search`,
      parent_embed_id: "fa3654bf-3653-436c-9077-2a2f41816f0c",
      embed_ids: null,
    },
    {
      embed_id: "b5a438b1-a8d4-4de4-bf51-2c982c0caf72",
      type: "website",
      content: `type: search_result
title: "Artemis II Flight Day 7: First Return Correction Burn Complete - NASA"
url: "https://www.nasa.gov/blogs/missions/2026/04/07/artemis-ii-flight-day-7-first-return-correction-burn-complete/"
description: "At 8:03 p.m. EDT, the Orion spacecraft, named Integrity, ignited its thrusters for 15 seconds, producing a change in velocity of 1.6 feet-per-second and guiding the Artemis II crew toward Earth. NASA astronaut Christina Koch and CSA (Canadian Space Agency) astronaut Jeremy Hansen reviewed procedures and monitored the spacecraft’s configuration and navigation data. During today’s mission status briefing, NASA officials shared the first images received from the crew during the lunar flyby and confirmed that the USS John P."
page_age: 4 days ago
profile_name: NASA
meta_url_favicon: "https://imgs.search.brave.com/BBFmCMg1UgOoUD0FzIwQhKfBIT1COEbSGDOOGQbY_i8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNDNlNTRkMjE4/NjM5MTUzOGQ4ZDI2/ZjdiYjMyZTA5OGY2/NDhlOTBjNTY4MDk5/ZjVjZjkyOGZmZGRl/ZjFiYjlmZS93d3cu/bmFzYS5nb3Yv"
thumbnail_src: "https://imgs.search.brave.com/ecXn92WG6wxIY5kL4VaMERs1kXDSYOCqKIUsxa2fk2w/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/bmFzYS5nb3Yvd3At/Y29udGVudC91cGxv/YWRzLzIwMjYvMDQv/cnRjLTEtYnJvYWRj/YXN0LnBuZw"
thumbnail_original: "https://www.nasa.gov/wp-content/uploads/2026/04/rtc-1-broadcast.png"
extra_snippets: "April 7, 2026 9:54PM · A live view shows the Orion spacecraft and its solar arrays as the Artemis II crew completed the mission’s first return correction burn on Flight Day 7. At 8:03 p.m. EDT, the Orion spacecraft, named Integrity, ignited its thrusters for 15 seconds, producing a change in velocity of 1.6 feet-per-second and guiding the Artemis II crew toward Earth.|View the latest imagery from the Artemis II mission on our Artemis II Multimedia Resource Page. Please follow @NASAArtemis on X, Facebook, and Instagram for real-time updates. Live mission coverage is available on NASA’s YouTube channel. Linda E. Grimm · Joseph Zakrzewski · NASA Communications · April 7, 2026 9:54PM|At 8:03 p.m. EDT, the Orion spacecraft, named Integrity, ignited its thrusters for 15 seconds, producing a change in velocity of 1.6 feet-per-second and guiding the Artemis II crew toward Earth. NASA astronaut Christina Koch and CSA (Canadian Space Agency) astronaut Jeremy Hansen reviewed procedures and monitored the spacecraft’s configuration and navigation data. During today’s mission status briefing, NASA officials shared the first images received from the crew during the lunar flyby and confirmed that the USS John P.|The agency will provide updates on recovery operations and weather during the daily Mission Status briefings. Looking ahead, the crew will settle in for a full night’s rest before a busy day of flight test objectives and return to Earth tasks on Wednesday, April 8."
hash: cdf3358e0a3306e5
embed_ref: nasa.gov-YZQ
app_id: web
skill_id: search`,
      parent_embed_id: "fa3654bf-3653-436c-9077-2a2f41816f0c",
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 2,
  },
  wikipedia_topics: [
    { topic: "Artemis program", wiki_title: "Artemis program", wikidata_id: "Q63819987", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/3/31/Artemis_program_%28solid_contrast_with_wordmark%29.svg/330px-Artemis_program_%28solid_contrast_with_wordmark%29.svg.png", description: "NASA-led lunar exploration program" },
    { topic: "Space Launch System", wiki_title: "Space Launch System", wikidata_id: "Q64127", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b1/Artemis_II_launch_%28SLS_MAF_20260401_ArtemisIILaunch_02%29_crop.jpg/330px-Artemis_II_launch_%28SLS_MAF_20260401_ArtemisIILaunch_02%29_crop.jpg", description: "NASA super heavy-lift expendable launch vehicle" },
    { topic: "Orion", wiki_title: "Orion (spacecraft)", wikidata_id: "Q211727", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/5/52/Orion_Snaps_a_Selfie_During_External_Inspection_%28vertical%29.jpg/330px-Orion_Snaps_a_Selfie_During_External_Inspection_%28vertical%29.jpg", description: "Artemis program crewed spacecraft" },
    { topic: "Reid Wiseman", wiki_title: "Reid Wiseman", wikidata_id: "Q3116390", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7b/Jsc2023e0016434_alt.jpg/330px-Jsc2023e0016434_alt.jpg", description: "American aviator and astronaut (born 1975)" },
    { topic: "Victor Glover", wiki_title: "Victor Glover", wikidata_id: "Q13499227", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/Jsc2023e0016433_alt.jpg/330px-Jsc2023e0016433_alt.jpg", description: "American astronaut (born 1976)" },
    { topic: "Christina Koch", wiki_title: "Christina Koch", wikidata_id: "Q13500192", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Jsc2023e0016435_alt.jpg/330px-Jsc2023e0016435_alt.jpg", description: "American astronaut (born 1979)" },
    { topic: "Jeremy Hansen", wiki_title: "Jeremy Hansen", wikidata_id: "Q1687593", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/5/50/Jsc2023e0016436_alt2.jpg/330px-Jsc2023e0016436_alt2.jpg", description: "Canadian astronaut (born 1976)" },
    { topic: "Apollo 13", wiki_title: "Apollo 13", wikidata_id: "Q182252", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/Apollo_13-insignia.png/330px-Apollo_13-insignia.png", description: "Aborted Moon landing mission in the Apollo program" },
    { topic: "Kennedy Space Center", wiki_title: "Kennedy Space Center", wikidata_id: "Q48821", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/NASA_logo.svg/330px-NASA_logo.svg.png", description: "NASA launch facility in Florida" },
    { topic: "Lunar Gateway", wiki_title: "Lunar Gateway", wikidata_id: "Q29098442", thumbnail_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Lunar_Gateway_rendering_2.webp/330px-Lunar_Gateway_rendering_2.webp.png", description: "Cancelled lunar orbital space station" },
  ],
};