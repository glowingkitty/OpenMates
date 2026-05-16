---
name: create-video
description: Create OpenMates marketing videos from script notes using the external Remotion workspace, product-accurate UI rebuilds, optional Playwright recordings, renders, and review uploads.
user-invocable: true
argument-hint: "<script note path | video idea> [official|personal] [square|vertical|horizontal]"
---

## Overview

Use this skill to turn an OpenMates marketing video idea or script note into a first reviewable video draft.

Primary workspace:

`/home/superdev/projects/openmates-marketing/videos/remotion`

Do not create Remotion projects, renders, `node_modules`, or source videos inside the main OpenMates repo unless the user explicitly asks. The OpenMates repo is the product source of truth; the marketing repo is the video production workspace.

## Inputs

Accept any of these:

- Obsidian script note path under `vaults/memory/Areas/marketing/videos/`.
- Pasted video script.
- A rough video idea.
- Existing Remotion composition to revise.

If the input is a rough idea, first create or update a script note in:

`vaults/memory/Areas/marketing/videos/`

Use existing marketing context:

- `vaults/memory/Areas/marketing/communication-strategy.md`
- `vaults/memory/Areas/marketing/videos/marketing-videos.md`
- `vaults/memory/Areas/marketing/videos/Your privacy matters, especially in the age of AI chatbots.md`

## Default Output

Unless the user says otherwise:

- Format: `1080x1080` square-safe.
- FPS: `30`.
- Duration: about `30s`.
- Style: mobile-first, large text, fast pacing, short on-screen copy.
- Render path: `/home/superdev/projects/openmates-marketing/videos/remotion/renders/<slug>.mp4`.
- Review upload: public temporary Hetzner Object Storage URL.

## Accuracy Rules

- Do not invent product capabilities.
- Avoid privacy overclaims such as "the AI never sees your data", "server never sees your messages", or "all chats are end-to-end encrypted" unless the current implementation and approved communication strategy support the exact claim.
- Prefer specific, demonstrable feature language: "Replaced before AI", "Choose what to hide", "Restore in your UI", "Less data shared".
- If a visual claims real product behavior, prefer a real UI recording or a faithful focused rebuild from source components.
- Make uncertainty visible in the script or ask the user before rendering.

## Production Strategy

Choose the simplest source that proves the beat.

Use Remotion React rebuilds for:

- Title cards.
- Animated diagrams.
- Focused single UI components.
- Cropped/zoomed product moments where the full app would be too small.
- Placeholder, highlight, cursor, and caption overlays.

Use Playwright recordings for:

- Multi-component flows.
- Product behavior that must be visibly real.
- Broader app context where a rebuild would risk drift.

Do not record:

- Login.
- Signup.
- Email verification.
- Passkey prompts.
- Account setup.
- Test account emails, secrets, or unrelated chat history.

Start recordings only after the authenticated product state is ready and stable.

## Visual Source Of Truth

When rebuilding UI, read the real Svelte/CSS source first and cite it in the file header.

Common sources:

- Background: `frontend/packages/ui/src/components/ChatHeader.svelte`
- Tokens: `frontend/packages/ui/src/tokens/generated/theme.generated.css`
- Message input: `frontend/packages/ui/src/components/enter_message/MessageInput.svelte`
- Action buttons: `frontend/packages/ui/src/components/enter_message/ActionButtons.svelte`
- PII banner: `frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte`
- Chat messages: `frontend/packages/ui/src/components/ChatMessage.svelte`
- PII toggle: `frontend/packages/ui/src/components/ActiveChat.svelte` (`data-testid="chat-pii-toggle"`)

For OpenMates gradient backgrounds, match the `ChatHeader.svelte` processing state:

- Base gradient: `#4867cd` to `#5a85eb`.
- Orb colors: `#4867cd` and `#a0beff`.
- Three soft radial orb layers.
- Blur around `28px`.
- Continuous slow motion, not a static flat background.

Use Lexend Deca for marketing text. Load it in the Remotion project if it is not already available.

## Workflow

1. Read the script or idea and identify the channel: official OpenMates or personal founder.
2. Read the communication strategy and relevant script notes.
3. Break the video into beats with timestamps, on-screen text, source strategy, and claim risk.
4. Confirm whether any beat needs Playwright recording. If yes, write a recording plan before implementation.
5. Inspect existing Remotion files in `/home/superdev/projects/openmates-marketing/videos/remotion`.
6. Reuse existing components before creating new ones.
7. Add a focused composition under `src/compositions/`.
8. Register the composition in `src/Root.tsx`.
9. Add an npm render script in `package.json`.
10. Render still frames at key beats before doing a full render.
11. Fix obvious layout, font, crop, claim, and readability issues.
12. Render the MP4.
13. Check duration and file size.
14. Upload for review.
15. Return the review URL, changed files, render path, and known draft issues.

## Remotion Commands

Use the external marketing workspace:

```bash
cd /home/superdev/projects/openmates-marketing/videos/remotion
```

Type-check:

```bash
npm exec tsc -- --noEmit
```

Render a still frame:

```bash
npm exec remotion -- still src/index.ts <CompositionId> renders/<slug>-frame-<frame>.png --frame=<frame>
```

Render a video:

```bash
npm run render:<slug>
```

Check output:

```bash
ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1:nokey=0 "renders/<slug>.mp4"
```

## Upload Review MP4

Preferred upload path uses the running `api` container and Vault-backed Hetzner credentials. Never print secret values.

Copy the MP4 into the container:

```bash
docker cp "renders/<slug>.mp4" api:/tmp/<slug>.mp4
```

Upload inside the container:

```bash
docker exec api python -c $'import asyncio, hashlib\nfrom pathlib import Path\nimport boto3\nfrom backend.core.api.app.utils.secrets_manager import SecretsManager\nasync def main():\n    slug = "<slug>"\n    path = Path(f"/tmp/{slug}.mp4")\n    content = path.read_bytes()\n    digest = hashlib.md5(content).hexdigest()\n    key = f"buffer-media/{digest}-{slug}.mp4"\n    manager = SecretsManager()\n    await manager.initialize()\n    secrets = await manager.get_secrets_from_path("kv/data/providers/hetzner")\n    region = (secrets or {}).get("s3_region_name") or "nbg1"\n    client = boto3.client("s3", endpoint_url=f"https://{region}.your-objectstorage.com", aws_access_key_id=secrets["s3_access_key"], aws_secret_access_key=secrets["s3_secret_key"], region_name=region)\n    client.put_object(Bucket="openmates-buffer-media", Key=key, Body=content, ContentType="video/mp4", ACL="public-read")\n    print(f"https://openmates-buffer-media.{region}.your-objectstorage.com/{key}")\nasyncio.run(main())'
```

If this upload path fails because the `api` container is unavailable, stop and report the blocker. Do not paste local S3 keys into the shell.

## Review Checklist

Before returning a draft URL, inspect still frames for:

- Text readable on mobile.
- Important content inside the central safe area.
- Lexend Deca loaded and visually applied.
- UI not cropped unexpectedly.
- Placeholder/reveal animations do not leave invisible text gaps.
- Background matches OpenMates blue gradient/orb language.
- Claims are accurate and not overbroad.
- Video starts quickly and does not waste the first second.
- Product UI is large enough to understand without pausing.

## Output Format

Return:

```markdown
## Video Draft

Review URL: <url>

Source:
- Script: <path or pasted input>
- Composition: <path>
- Render: <path>

Verification:
- Type-check: <passed|not run + reason>
- Render: <duration, size>
- Still-frame review: <frames checked>

Known Draft Issues:
- <issue or "None obvious from still-frame review">

Next Iteration Suggestions:
1. ...
2. ...
3. ...
```

## Common Pitfalls

- Do not create video source under `OpenMates/scripts/marketing_videos/`.
- Do not show full app chrome when a focused UI crop is clearer.
- Do not use tiny captions or long paragraphs.
- Do not rely on static screenshots when a simple Remotion animation explains the feature better.
- Do not use Playwright recordings for auth/setup flows.
- Do not leave temporary `node_modules` or generated renders in the OpenMates repo.
- Do not commit or deploy unless the user explicitly asks.
