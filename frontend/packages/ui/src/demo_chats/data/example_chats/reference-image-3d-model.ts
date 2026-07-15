// frontend/packages/ui/src/demo_chats/data/example_chats/reference-image-3d-model.ts
//
// Example chat: Reference Image to 3D Model
// Uses a recovered real Hi3D generation poster, stripped of private storage
// keys and user-specific metadata so the fixture is safe to ship publicly.

import type { ExampleChat } from "../../types";

const MODEL3D_POSTER_DATA_URL =
  "data:image/webp;base64,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";

export const referenceImage3DModelChat: ExampleChat = {
  chat_id: "example-reference-image-3d-model",
  slug: "reference-image-3d-model",
  title: "example_chats.reference_image_3d_model.title",
  summary: "example_chats.reference_image_3d_model.summary",
  icon: "3dmodels",
  category: "design",
  keywords: ["3D model generation", "image to 3D", "Hi3D", "GLB", "product design"],
  follow_up_suggestions: [],
  messages: [
    {
      id: "c79b9ff0-7d58-4ed7-b860-4c427cdab6bd",
      role: "user",
      content: "example_chats.reference_image_3d_model.message_1",
      created_at: 1784071246,
    },
    {
      id: "fbf595b9-2f71-4a7a-b544-56529bf9a38d",
      role: "assistant",
      content: "example_chats.reference_image_3d_model.message_2",
      created_at: 1784071268,
      category: "design",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "85716124-48d5-4c4c-9919-3126b733b41e",
      type: "app_skill_use",
      content: `app_id: models3d
skill_id: generate
type: model3d
status: finished
input_mode: image
prompt: "Create a textured 3D GLB model from the uploaded reference image."
provider: Hi3D
provider_model: Hi3D
poster_url: "${MODEL3D_POSTER_DATA_URL}"
files:
  master:
    size_bytes: 25847448
    format: glb
    mime_type: model/gltf-binary
  poster:
    size_bytes: 20690
    format: webp
    mime_type: image/webp
  preview:
    size_bytes: 25847448
    format: glb
    mime_type: model/gltf-binary
    optimized: false
    fallback_reason: preview_optimization_failed
generated_at: "2026-07-14T23:20:46+00:00"
provenance:
  ai_generated: true
  labeling: static_public_fixture`,
      parent_embed_id: null,
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 38,
    app_skill_examples: ["models3d.generate"],
  },
};
