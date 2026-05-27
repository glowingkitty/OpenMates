/**
 * App-store examples for the music/generate skill.
 *
 * Uses a real generated Google Lyria audio asset saved as a static MP3 in
 * frontend/apps/web_app/static/store-examples/. The preview/fullscreen
 * components load it via `previewAudioUrl`, bypassing the normal encrypted S3
 * media pipeline used by real chat embeds.
 */

export interface MusicGenerateStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  prompt: string;
  mode: string;
  durationSeconds: number;
  duration_seconds: number;
  model: string;
  provider: string;
  status: 'finished';
  previewAudioUrl: string;
  files: { original: Record<string, unknown> };
  generated_at: string;
  watermarking: string;
}

const examples: MusicGenerateStoreExample[] = [
  {
    "id": "store-example-music-generate-1",
    "query": "Warm lo-fi writing loop",
    "query_translation_key": "settings.app_store_examples.music.generate.1",
    "prompt": "Warm lo-fi background loop for focused writing, soft Rhodes chords, brushed drums, mellow bass, no vocals",
    "mode": "loop",
    "durationSeconds": 30,
    "duration_seconds": 30,
    "model": "lyria-3-clip-preview",
    "provider": "Google Vertex AI",
    "status": "finished",
    "previewAudioUrl": "/store-examples/music-generate-1.mp3",
    "files": {
      "original": {
        "size_bytes": 725172,
        "format": "mp3",
        "mime_type": "audio/mpeg",
        "duration_seconds": 30
      }
    },
    "generated_at": "2026-05-24T17:45:18.014295+00:00",
    "watermarking": "SynthID"
  }
];

export default examples;
