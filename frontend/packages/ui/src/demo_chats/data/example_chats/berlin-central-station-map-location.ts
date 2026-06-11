// frontend/packages/ui/src/demo_chats/data/example_chats/berlin-central-station-map-location.ts
//
// Example chat: Berlin Central Station Map Location
// Public static example for the maps.location content catalog item.
// Coordinates are for a public landmark and no user location is included.

import type { ExampleChat } from "../../types";

export const berlinCentralStationMapLocationChat: ExampleChat = {
  chat_id: "example-berlin-central-station-map-location",
  slug: "berlin-central-station-map-location",
  title: "Berlin Central Station Map Location",
  summary: "Save Berlin Central Station as a reusable map location card with public address metadata.",
  icon: "maps",
  category: "general_knowledge",
  keywords: ["map location", "Berlin", "station", "travel planning", "public landmark"],
  follow_up_suggestions: [],
  messages: [
    {
      id: "e4096878-c418-4bb4-ab07-0379fa240810",
      role: "user",
      content: "Pin Berlin Central Station so I can refer to it while planning a train transfer.",
      created_at: 1781000400,
    },
    {
      id: "7ea31c97-2ffe-4fe4-8d57-d63d2e4eb5ab",
      role: "assistant",
      content: "```json\n{\"type\":\"maps\",\"embed_id\":\"b66e28f5-a8e4-4d52-9cc5-5ef52c61d205\",\"app_id\":\"maps\",\"skill_id\":\"location\"}\n```\n\nI pinned Berlin Central Station with its public address and coordinates so it can be reused in the trip plan.",
      created_at: 1781000468,
      category: "general_knowledge",
      model_name: "Gemini 3.1 Pro",
    },
  ],
  embeds: [
    {
      embed_id: "b66e28f5-a8e4-4d52-9cc5-5ef52c61d205",
      type: "maps",
      content: "type: maps\napp_id: maps\nskill_id: location\nname: Berlin Hauptbahnhof\naddress: Europaplatz 1, 10557 Berlin, Germany\nlocation_type: precise_location\nplace_type: railway\nlatitude: 52.525084\nlongitude: 13.369402\nembed_ref: berlin-hauptbahnhof-b66e28\nstatus: finished",
      parent_embed_id: null,
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 39,
    content_embed_examples: ["maps.location"],
  },
};
