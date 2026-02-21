# Images App Architecture

The Images app provides advanced image generation, manipulation, and analysis capabilities within OpenMates.

## Technical Architecture

### Embed-Based Storage Model

Every generated image is stored as an **embed** (see [Embeds Architecture](../architecture/embeds.md)). This provides a unified model for both REST API and Web App access, with consistent encryption, status tracking, and cross-chat referencing capabilities.

**Key Benefits:**

- Same data model for REST API and Web App
- Reuses existing embeds infrastructure (status tracking, encryption, sharing)
- Generic download endpoint works for any embed with file attachments
- Future-proof for generated audio, video, PDFs, etc.

### Asynchronous Execution Flow

Image generation is a long-running process (>5s) and follows a strictly asynchronous pattern:

**REST API Flow:**

1. `POST /v1/apps/images/generate` dispatches a Celery task to `app_images` queue
2. Response includes `task_id` and `embed_id` (embed created with `status: "processing"`)
3. Client polls `GET /v1/tasks/{task_id}` to monitor progress
4. When complete, poll response includes `embed_id` and file metadata
5. Client downloads via `GET /v1/embeds/{embed_id}/file?format=preview|full|original`

**Web App Flow:**

1. Skill invocation creates embed placeholder via WebSocket (status: "processing")
2. Celery task processes in background
3. On completion, `embed_update` WebSocket event sent to client
4. Client renders `ImageEmbedPreview` using preview format
5. On click, fullscreen view requests full format

### Embed Content Structure

Generated image embeds store their content in the following structure (within `encrypted_content`):

```json
{
  "type": "image",
  "files": {
    "preview": {
      "s3_key": "user123/20260117_abc_preview.webp",
      "width": 600,
      "height": 400,
      "size_bytes": 45000,
      "format": "webp"
    },
    "full": {
      "s3_key": "user123/20260117_abc_full.webp",
      "width": 1920,
      "height": 1080,
      "size_bytes": 230000,
      "format": "webp"
    },
    "original": {
      "s3_key": "user123/20260117_abc_original.png",
      "width": 1920,
      "height": 1080,
      "size_bytes": 1200000,
      "format": "png"
    }
  },
  "encrypted_aes_key": "vault-wrapped-aes-key",
  "aes_nonce": "base64-nonce",
  "prompt": "A futuristic cityscape at sunset",
  "model": "google/gemini-3-pro-image-preview",
  "aspect_ratio": "16:9",
  "generated_at": "2026-01-17T12:00:00Z"
}
```

### Storage & Security

All generated images are secured using a **Hybrid Encryption** model (same pattern as invoice PDFs):

- **Encryption Mode**: Generated embeds use `encryption_mode: "vault"`. This allows the server to decrypt metadata (like the prompt and S3 keys) for background tasks and the REST API, while still keeping it encrypted at rest in Directus using user-specific Vault keys.
- **Bucket**: Files are stored in the centralized `chatfiles` bucket.
- **Obfuscation**: No specific prefixes (like `generated/`) are used at the storage layer to ensure server admins cannot distinguish between uploaded and generated content.
- **Encryption**:
  - A unique AES-256-GCM key is generated per image set (all 3 formats share the same key).
  - This AES key is wrapped (encrypted) using the user's Vault key.
  - The image payload is encrypted before being uploaded to S3 as `application/octet-stream`.
  - On download, the server decrypts using Vault and streams the plaintext image.
- **Multi-Format Processing**: For every generation, the system produces three versions:
  1. **Original**: The raw output from the provider (usually PNG)
  2. **Full WEBP**: A high-quality compressed version for web delivery and editing
  3. **Preview WEBP**: A scaled-down version (max 600x400) for the `ImageEmbedPreview` component

### Hybrid Access Flow

Since embeds are typically client-side encrypted (Zero-Knowledge), but generated images use Vault encryption (Server-Managed), the system implements a hybrid access flow:

1. **REST API / AI Engine**: Can access metadata and files immediately using Vault decryption.
2. **Web App**:
   - Detects `encryption_mode: "vault"` on an embed.
   - Realizes it doesn't have an `embed_key` in the `embed_keys` collection.
   - Calls `GET /v1/embeds/{embed_id}/content` to fetch the decrypted metadata from the server.
   - This allows the AI to "see" its own previous generations even if the user is offline, while still maintaining encryption-at-rest.

### Endpoints

#### Download File

```http
GET /v1/embeds/{embed_id}/file?format=preview|full|original
Authorization: Bearer {api_key} OR Session Cookie

Response: image/webp or image/png (decrypted image bytes)
```

#### Get Decrypted Metadata

```http
GET /v1/embeds/{embed_id}/content
Authorization: Bearer {api_key} OR Session Cookie

Response: JSON object (decrypted embed content)
```

## Providers & Models

### High-End Generation

- **Provider**: Google (via `google-genai` SDK / AI Studio)
- **Model**: `gemini-3-pro-image-preview`
- **Features**: Optimized for complex prompt adherence, high aesthetic quality, and 1K resolution.

### Draft Generation

- **Provider**: Black Forest Labs (via `fal.ai` REST API)
- **Model**: `fal-ai/flux-2/klein/9b/base`
- **Features**: Optimized for speed and efficiency, providing a "vibe-check" or draft version at ~10x lower cost.

## UI/UX Components

### Embedded Previews

#### Image

Used every time an image is contained in a message in the chat history or message input field.
For uploaded images, generated images, and images from web search results.

#### Image | Fullscreen view

Shows the image in fullscreen with the image name, file type, and size.

Editing options:

- Crop image
- Draw simple shapes on image (to ask about something circled in an image) & mark areas for editing

### Skill "Generate image"

Shows prompt and model used for generation, with an estimated finish time. Once finished, the image displays an AI icon in the top right (fades out after a few seconds).

**Important: Publishing & AI Detection Safety**
Users must be instructed to:

- Review images for artifacts before publication.
- Report inconsistencies for regeneration.

**Metadata Removal & AI Labeling**

Before any external processing, all privacy-sensitive EXIF metadata (GPS, etc.) is stripped. However, the system injects industry-standard AI content signals:

- **IPTC 2025.1 Compliance**: Injects `DigitalSourceType: trainedAlgorithmicMedia`, `aiSystemUsed`, and `aiPromptInformation`.
- **Native C2PA Provenance**: Injects signed C2PA manifests using the `c2pa` library. This provides a cryptographically verifiable record of the image's origin.
  - **Signing**: Images are signed using an ES256 digital certificate generated for the OpenMates instance.
  - **Assertions**:
    - `c2pa.training-mining`: Explicitly sets both `ai_generative` and `ai_training` to `constrained` status.
    - `staxel.ai_metadata`: Stores the generation model, prompt, and timestamp.
    - `digital_source_type`: Links to the IPTC `trainedAlgorithmicMedia` standard.
  - **Coverage**: Applied to both the `original` provider output and the high-quality `full` WEBP version.
- **Invisible Watermarking**: Preserves provider-level signals (like Google SynthID) by using high-quality encoding (90+) for the full-resolution version.
- **Transparency**: Includes `CreatorTool` (OpenMates) and `Credit` info in the metadata.

#### Skill "Reverse image search"

- Uses Google Image search API (via SerpApi) for high-quality visual discovery.

---

## Planned: Image Editing Skills (Recraft API)

The following skills are planned as **separate images app skills** using the [Recraft API](https://www.recraft.ai/docs/api-reference/pricing). Each will be its own skill (not part of `images.generate`) to keep routing logic clean and billing transparent. None of these are implemented yet.

All planned skills below use Recraft V3 models (the editing endpoints are V3-only per Recraft's API).

### `images.edit_inpaint` — Inpainting (erase and redraw a region)

Fill or replace a masked region of an image using a text prompt.

- **Recraft endpoint**: image inpainting
- **Models / costs**:
  - Raster: `recraftv3` — $0.04/image (API cost)
  - Vector: `recraftv3_vector` — $0.08/image (API cost)
- **Inputs**: source image, mask image, text prompt, output_filetype
- **Use case**: remove objects, fix artifacts, replace backgrounds in a specific area

### `images.edit_replace_background` — Background replacement

Replace the entire background of an image while preserving the foreground subject.

- **Recraft endpoint**: replace background
- **Models / costs**:
  - Raster: `recraftv3` — $0.04/image (API cost)
  - Vector: `recraftv3_vector` — $0.08/image (API cost)
- **Inputs**: source image, text prompt describing the new background
- **Use case**: product photography, portrait backgrounds, scene transplants

### `images.edit_generate_background` — Background generation (subject-aware)

Generate a contextually fitting background around a subject without an explicit prompt — Recraft infers the scene.

- **Recraft endpoint**: generate background
- **Models / costs**:
  - Raster: `recraftv3` — $0.04/image (API cost)
  - Vector: `recraftv3_vector` — $0.08/image (API cost)
- **Inputs**: source image (subject/foreground extracted)
- **Use case**: seamless background synthesis for cut-out subjects

### `images.edit_image_to_image` — Image-to-image transformation

Transform an existing image using a text prompt (style transfer, scene modification, etc.).

- **Recraft endpoint**: image to image
- **Models / costs**:
  - Raster: `recraftv3` — $0.04/image (API cost)
  - Vector: `recraftv3_vector` — $0.08/image (API cost)
- **Inputs**: source image, text prompt, strength parameter
- **Use case**: restyling, converting a sketch to a rendered scene, variant generation

### `images.edit_erase_region` — Region eraser

Erase a masked region of the image (fills with contextually aware content or transparent pixels).

- **Recraft endpoint**: erase region
- **Cost**: $0.002/request (API cost) — very cheap utility operation
- **Inputs**: source image, mask image
- **Use case**: remove unwanted objects, clean up images

### `images.variate` — Image variation

Generate a variation of an existing image while preserving its general composition.

- **Recraft endpoint**: variate image
- **Cost**: $0.04/request (API cost)
- **Inputs**: source image, optional strength/seed
- **Use case**: A/B testing variations, exploring alternatives from a base generation

### `images.upscale` — Image upscaling

Upscale an image to a higher resolution using one of two modes:

| Mode       | Endpoint         | Cost           | Description                                                               |
| ---------- | ---------------- | -------------- | ------------------------------------------------------------------------- |
| `crisp`    | crisp upscale    | $0.004/request | Fast upscale, preserves hard edges — best for UI/icons/vector-style art   |
| `creative` | creative upscale | $0.25/request  | AI-enhanced upscale that adds detail — best for photos and complex scenes |

- **Inputs**: source image, mode (`crisp` \| `creative`)
- **Use case**: prepare images for print, enhance low-res assets

### `images.remove_background` — Background removal

Remove the background from an image to produce a transparent PNG.

- **Recraft endpoint**: image background removal
- **Cost**: $0.01/request (API cost)
- **Inputs**: source image
- **Use case**: product photography, sticker creation, compositing

### `images.vectorize` — Raster-to-vector conversion

Convert an existing raster image (PNG/JPG) to a scalable SVG vector.

- **Recraft endpoint**: image vectorization
- **Cost**: $0.01/request (API cost)
- **Inputs**: source image (PNG/JPG)
- **Use case**: convert logos, icons, or illustrations to infinitely scalable SVG

### `images.create_style` — Style creation

Create a reusable Recraft style from reference images. The resulting style ID can be passed to future `images.generate` calls to apply a consistent visual style.

- **Recraft endpoint**: image style creation
- **Cost**: $0.04/request (API cost)
- **Inputs**: one or more reference images
- **Output**: a `style_id` string stored on the user's account
- **Use case**: brand consistency, series of images with a unified aesthetic
