/**
 * App-store examples for the videos/generate skill.
 *
 * Uses a real generated Google Veo video asset saved as a static MP4 in
 * frontend/apps/web_app/static/store-examples/. The preview/fullscreen
 * components load it via `previewVideoUrl`, bypassing the normal encrypted S3
 * media pipeline used by real chat embeds.
 */

export interface VideoGenerateStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  prompt: string;
  durationSeconds: number;
  duration_seconds: number;
  aspect_ratio: string;
  resolution: string;
  model: string;
  provider: string;
  status: 'finished';
  previewVideoUrl: string;
  files: { original: Record<string, unknown> };
  generated_at: string;
  watermarking: string;
}

const examples: VideoGenerateStoreExample[] = [
  {
    "id": "store-example-videos-generate-1",
    "query": "Alpine sunrise meadow",
    "query_translation_key": "settings.app_store_examples.videos.generate.1",
    "prompt": "A gentle cinematic shot of sunrise light moving across a quiet alpine meadow with distant mountains, realistic camera movement, no text",
    "durationSeconds": 8,
    "duration_seconds": 8,
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "model": "veo-3.1-fast-generate-preview",
    "provider": "Google Gemini API",
    "status": "finished",
    "previewVideoUrl": "/store-examples/video-generate-1.mp4",
    "files": {
      "original": {
        "size_bytes": 11473361,
        "format": "mp4",
        "mime_type": "video/mp4",
        "duration_seconds": 8
      }
    },
    "generated_at": "2026-05-24T17:46:38.435925+00:00",
    "watermarking": "SynthID"
  }
];

export default examples;
