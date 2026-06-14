// frontend/packages/ui/src/demo_chats/data/example_chats/damped-sine-wave-plot.ts
//
// Example chat: Damped Sine Wave Plot
// Public static example for the math.plot content catalog item.
// The embed contains only a small plot specification and no private data.

import type { ExampleChat } from "../../types";

export const dampedSineWavePlotChat: ExampleChat = {
  chat_id: "example-damped-sine-wave-plot",
  slug: "damped-sine-wave-plot",
  title: "Damped Sine Wave Plot",
  summary: "Plot a damped sine wave and compare it with the positive and negative envelopes.",
  icon: "function",
  category: "science",
  keywords: ["math plot", "damped sine", "function graph", "envelope", "visualization"],
  follow_up_suggestions: [],
  messages: [
    {
      id: "08120f35-c67f-4da6-85f6-7621d14ae320",
      role: "user",
      content: "Plot a damped sine wave f(x) = exp(-0.2x) * sin(3x) from 0 to 12, and include the positive and negative exponential envelopes.",
      created_at: 1781000200,
    },
    {
      id: "886d0941-5b50-4a76-a582-c7d9947db478",
      role: "assistant",
      content: "```json\n{\"type\":\"math-plot\",\"embed_id\":\"a7082ab8-8b27-4d43-b02d-351171c9a8cb\",\"app_id\":\"math\",\"skill_id\":\"plot\"}\n```\n\nHere is the plot setup with the damped oscillation and both envelopes. Open the plot to inspect the full graph range.",
      created_at: 1781000261,
      category: "science",
      model_name: "Gemini 3.1 Pro",
    },
  ],
  embeds: [
    {
      embed_id: "a7082ab8-8b27-4d43-b02d-351171c9a8cb",
      type: "math-plot",
      content: "type: math-plot\napp_id: math\nskill_id: plot\nplot_spec: \"f(x) = exp(-0.2 * x) * sin(3 * x)\\ng(x) = exp(-0.2 * x)\\nh(x) = -exp(-0.2 * x)\"\nembed_ref: damped-sine-a7082a\nstatus: finished",
      parent_embed_id: null,
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 38,
    content_embed_examples: ["math.plot"],
  },
};
