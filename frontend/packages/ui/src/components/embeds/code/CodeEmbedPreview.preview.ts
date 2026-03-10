/**
 * Preview mock data for CodeEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/code/CodeEmbedPreview
 */

const sampleCode = `import { onMount } from 'svelte';

interface Props {
  title: string;
  count?: number;
}

let { title, count = 0 }: Props = $props();
let isLoading = $state(false);
let displayTitle = $derived(title.toUpperCase());

onMount(() => {
  console.log('Component mounted');
});`;

/** Default props — shows a finished code embed with TypeScript/Svelte content */
const defaultProps = {
	id: 'preview-code-1',
	language: 'typescript',
	filename: 'MyComponent.svelte',
	lineCount: 14,
	status: 'finished' as const,
	codeContent: sampleCode,
	isMobile: false,
	onFullscreen: () => {}
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading/streaming animation */
	processing: {
		id: 'preview-code-processing',
		language: 'python',
		filename: 'main.py',
		lineCount: 0,
		status: 'processing' as const,
		codeContent: '',
		isMobile: false
	},

	/** Bash script example */
	bash: {
		id: 'preview-code-bash',
		language: 'bash',
		filename: 'deploy.sh',
		lineCount: 18,
		status: 'finished' as const,
		codeContent: `#!/usr/bin/env bash
set -euo pipefail

APP_NAME="openmates-api"
REGISTRY="registry.example.com"
TAG="$(git rev-parse --short HEAD)"

echo "Building $APP_NAME:$TAG..."
docker build -t "$REGISTRY/$APP_NAME:$TAG" .

echo "Pushing to registry..."
docker push "$REGISTRY/$APP_NAME:$TAG"
docker tag "$REGISTRY/$APP_NAME:$TAG" "$REGISTRY/$APP_NAME:latest"
docker push "$REGISTRY/$APP_NAME:latest"

echo "Deploying to production..."
ssh deploy@prod "docker pull $REGISTRY/$APP_NAME:$TAG && docker-compose up -d"
echo "Deployment complete: $APP_NAME @ $TAG"`,
		isMobile: false
	},

	/** Extensive Python code example */
	python: {
		id: 'preview-code-python',
		language: 'python',
		filename: 'embed_service.py',
		lineCount: 42,
		status: 'finished' as const,
		codeContent: `"""
Embed resolution service — resolves embed references in AI responses.
See docs/architecture/embeds.md for the full pipeline description.
"""
from __future__ import annotations
import asyncio
from typing import Any
from pydantic import BaseModel
from backend.shared.providers.redis import redis_client
from .embed_store import EmbedStore
from .embed_types import EmbedStatus

EMBED_TTL_SECONDS = 3600 * 24  # 24 hours


class EmbedContent(BaseModel):
    embed_id: str
    skill_id: str
    status: EmbedStatus
    content: dict[str, Any] | None = None


async def resolve_embed(embed_id: str) -> EmbedContent | None:
    """Resolve an embed by ID, checking Redis cache first."""
    cache_key = f"embed:{embed_id}"

    # 1. Try Redis cache (fast path)
    cached = await redis_client.get(cache_key)
    if cached:
        return EmbedContent.model_validate_json(cached)

    # 2. Fall back to persistent embed store
    store = EmbedStore()
    embed = await store.get(embed_id)
    if not embed:
        return None

    # 3. Warm the cache for subsequent requests
    await redis_client.setex(
        cache_key,
        EMBED_TTL_SECONDS,
        embed.model_dump_json()
    )
    return embed


async def resolve_embed_batch(
    embed_ids: list[str],
    concurrency: int = 10
) -> dict[str, EmbedContent | None]:
    """Resolve multiple embeds concurrently with a semaphore."""
    sem = asyncio.Semaphore(concurrency)

    async def _fetch(eid: str) -> tuple[str, EmbedContent | None]:
        async with sem:
            return eid, await resolve_embed(eid)

    results = await asyncio.gather(*[_fetch(eid) for eid in embed_ids])
    return dict(results)`,
		isMobile: false
	},

	/** Svelte 5 component */
	svelte: {
		id: 'preview-code-svelte',
		language: 'svelte',
		filename: 'EmbedCard.svelte',
		lineCount: 35,
		status: 'finished' as const,
		codeContent: `<!--
  EmbedCard.svelte — Reusable card component for embed previews.
  Uses container queries for responsive layout.
-->
<script lang="ts">
  import { fade } from 'svelte/transition';

  interface Props {
    title: string;
    subtitle?: string;
    status: 'loading' | 'ready' | 'error';
    appId: string;
    onOpen?: () => void;
  }

  let { title, subtitle = '', status, appId, onOpen }: Props = $props();

  let isHovered = $state(false);
  let gradientStyle = $derived(\`background: var(--color-app-\${appId})\`);
</script>

<div
  class="embed-card"
  class:hovered={isHovered}
  onmouseenter={() => (isHovered = true)}
  onmouseleave={() => (isHovered = false)}
  role="button"
  tabindex="0"
  onclick={onOpen}
>
  <div class="app-icon" style={gradientStyle}></div>
  <div class="card-content">
    <p class="title">{title}</p>
    {#if subtitle}
      <p class="subtitle" transition:fade={{ duration: 150 }}>{subtitle}</p>
    {/if}
  </div>
</div>`,
		isMobile: false
	},

	/** HTML with embedded CSS and JavaScript */
	html: {
		id: 'preview-code-html',
		language: 'html',
		filename: 'landing.html',
		lineCount: 48,
		status: 'finished' as const,
		codeContent: `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>OpenMates — AI Assistant</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; }
    body {
      font-family: 'Inter', system-ui, sans-serif;
      background: #0d0d0d;
      color: #f0f0f0;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }
    .hero {
      text-align: center;
      padding: 4rem 2rem;
    }
    .hero h1 {
      font-size: clamp(2rem, 6vw, 5rem);
      font-weight: 800;
      background: linear-gradient(135deg, #7c6eff, #a78bfa);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .cta {
      margin-top: 2rem;
      padding: 0.75rem 2.5rem;
      border-radius: 9999px;
      background: #7c6eff;
      color: #fff;
      font-size: 1.125rem;
      font-weight: 600;
      border: none;
      cursor: pointer;
      transition: transform 0.15s;
    }
    .cta:hover { transform: scale(1.05); }
  </style>
</head>
<body>
  <section class="hero">
    <h1>Your AI Companion</h1>
    <p>Research, code, create — all in one place.</p>
    <button class="cta" id="startBtn">Get started free</button>
  </section>
  <script>
    document.getElementById('startBtn').addEventListener('click', () => {
      window.location.href = '/signup';
    });
  </script>
</body>
</html>`,
		isMobile: false
	},

	/** JavaScript module */
	javascript: {
		id: 'preview-code-js',
		language: 'javascript',
		filename: 'eventBus.js',
		lineCount: 28,
		status: 'finished' as const,
		codeContent: `/**
 * Lightweight typed event bus for cross-component communication.
 * Usage: import { eventBus } from './eventBus';
 *        eventBus.on('embed:updated', handler);
 *        eventBus.emit('embed:updated', { id: '123' });
 */

class EventBus {
  #listeners = new Map();

  on(event, handler) {
    if (!this.#listeners.has(event)) {
      this.#listeners.set(event, new Set());
    }
    this.#listeners.get(event).add(handler);
    // Return unsubscribe function
    return () => this.#listeners.get(event)?.delete(handler);
  }

  emit(event, payload) {
    const handlers = this.#listeners.get(event);
    if (!handlers?.size) return;
    for (const h of handlers) {
      try { h(payload); }
      catch (e) { console.error(\`[EventBus] Error in "\${event}" handler:\`, e); }
    }
  }

  once(event, handler) {
    const unsub = this.on(event, (payload) => {
      unsub();
      handler(payload);
    });
    return unsub;
  }
}

export const eventBus = new EventBus();`,
		isMobile: false
	},

	/** CSS stylesheet */
	css: {
		id: 'preview-code-css',
		language: 'css',
		filename: 'embed-card.css',
		lineCount: 30,
		status: 'finished' as const,
		codeContent: `/* Embed card design system tokens and component styles */
:root {
  --card-radius: 1.875rem;
  --card-shadow-rest: 0 4px 16px rgba(0, 0, 0, 0.08);
  --card-shadow-hover: 0 12px 32px rgba(0, 0, 0, 0.16);
  --card-transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.embed-card {
  position: relative;
  border-radius: var(--card-radius);
  background-color: var(--color-grey-0);
  box-shadow: var(--card-shadow-rest);
  transition: var(--card-transition);
  overflow: hidden;
  cursor: pointer;
  container-type: inline-size;
}

.embed-card:hover {
  transform: scale(1.015) translateY(-2px);
  box-shadow: var(--card-shadow-hover);
}

.embed-card:active {
  transform: scale(0.99);
  box-shadow: var(--card-shadow-rest);
}

@container (min-width: 300px) {
  .embed-card .card-title {
    font-size: 1rem;
    -webkit-line-clamp: 2;
  }
}`,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-code-error',
		language: 'javascript',
		status: 'error' as const,
		codeContent: '',
		isMobile: false
	}
};
