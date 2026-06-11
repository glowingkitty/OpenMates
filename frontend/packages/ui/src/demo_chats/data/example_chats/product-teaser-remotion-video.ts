// frontend/packages/ui/src/demo_chats/data/example_chats/product-teaser-remotion-video.ts
//
// Example chat: Product Teaser Remotion Video
// Public static example for the videos.rendered_video content catalog item.
// It demonstrates an already-supported videos.create Remotion embed using a
// public static MP4 instead of private encrypted render storage metadata.

import type { ExampleChat } from "../../types";

const remotionSource = `import React from "react";
import { AbsoluteFill, Composition, Sequence, interpolate, useCurrentFrame } from "remotion";

const Scene: React.FC<{ label: string; accent: string }> = ({ label, accent }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(frame, [0, 45], [36, 0], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{
      alignItems: "center",
      justifyContent: "center",
      background: "linear-gradient(135deg, #07111f, #123f52)",
      color: "white",
      fontFamily: "Inter, sans-serif",
    }}>
      <div style={{
        border: \`2px solid \${accent}\`,
        borderRadius: 36,
        padding: "48px 72px",
        opacity,
        transform: \`translateY(\${y}px)\`,
        boxShadow: \`0 0 80px \${accent}55\`,
      }}>
        <h1 style={{ margin: 0, fontSize: 72 }}>{label}</h1>
      </div>
    </AbsoluteFill>
  );
};

const LaunchTeaser: React.FC = () => (
  <AbsoluteFill>
    <Sequence from={0} durationInFrames={75}><Scene label="Private by default" accent="#7dd3fc" /></Sequence>
    <Sequence from={75} durationInFrames={75}><Scene label="Tools in one chat" accent="#86efac" /></Sequence>
    <Sequence from={150} durationInFrames={90}><Scene label="Launch with confidence" accent="#c4b5fd" /></Sequence>
  </AbsoluteFill>
);

export const Root: React.FC = () => (
  <Composition id="LaunchTeaser" component={LaunchTeaser} durationInFrames={240} fps={30} width={1920} height={1080} />
);`;

export const productTeaserRemotionVideoChat: ExampleChat = {
  chat_id: "example-product-teaser-remotion-video",
  slug: "product-teaser-remotion-video",
  title: "Product Teaser Remotion Video",
  summary: "Create an editable Remotion source-backed launch teaser video from a short creative brief.",
  icon: "videos",
  category: "marketing_sales",
  keywords: ["Remotion", "rendered video", "product teaser", "motion graphics", "editable source"],
  follow_up_suggestions: [],
  messages: [
    {
      id: "0c9d7712-a144-43f4-9b85-899a1323aa01",
      role: "user",
      content: "Create a short Remotion launch teaser for a privacy-first AI workspace. Make it three clean scenes, 8 seconds total, with editable source code so I can rerender variants later.",
      created_at: 1781000000,
    },
    {
      id: "fb1ea05d-6b40-4ef9-9fb6-3b843bb71028",
      role: "assistant",
      content: "```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"e07d18e7-d814-4fa5-b13d-863d5560d012\",\"app_id\":\"videos\",\"skill_id\":\"create\"}\n```\n\nI created a Remotion source-backed video with three scenes: privacy, unified tools, and launch confidence. The embed keeps the editable source attached, so you can inspect the timeline and rerender later.",
      created_at: 1781000072,
      category: "marketing_sales",
      model_name: "Gemini 3.1 Pro",
    },
  ],
  embeds: [
    {
      embed_id: "e07d18e7-d814-4fa5-b13d-863d5560d012",
      type: "app_skill_use",
      content: `app_id: videos
skill_id: create
type: remotion-video
status: finished
filename: LaunchTeaser.tsx
summary: Editable three-scene product teaser video
current_source_version: 1
remotion_source: ${JSON.stringify(remotionSource)}
render_metadata:
  renderer: remotion
  fps: 30
  width: 1920
  height: 1080
  duration_seconds: 8
video_url: /store-examples/video-generate-1.mp4
embed_ref: launch-teaser-e07d18`,
      parent_embed_id: null,
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 37,
    app_skill_examples: ["videos.create"],
    content_embed_examples: ["videos.rendered_video"],
  },
};
