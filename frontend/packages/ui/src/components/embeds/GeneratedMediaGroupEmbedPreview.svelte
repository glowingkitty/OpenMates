<!-- Skill-use parent card for one invocation with zero or more generated children. -->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { fade } from 'svelte/transition';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../services/chatSyncService';
  import { decodeToonContent } from '../../services/embedResolver';
  import SvgEmbedImage from './code/SvgEmbedImage.svelte';
  import { imageGenerationAttribution } from './images/imageGenerationMetadata';
  import {
    EMPTY_GENERATION_REQUEST, EMPTY_SVG_DRAFT, childDraftContent, hasDrawableSvg, mergeSvgDraft,
    readGenerationRequest, readSvgDraft, svgDraftStageLabelKey, type GenerationRequestInfo, type SvgDraftState,
  } from './images/svgDraft';
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  import GeneratedMediaThumbnails from './GeneratedMediaThumbnails.svelte';
  import { generatedMediaChildIds } from './generatedMediaGroup';
  import { pinnedEmbedsOf } from '../../services/rustCore/embeds/messageEmbedVersion';

  interface Props {
    id: string;
    appId: string;
    skillId: string;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    resultCount?: number;
    childEmbedIds?: string[];
    /** Prompt supplied by the manifest; otherwise taken from the first child. */
    prompt?: string;
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, appId, skillId, status, resultCount, childEmbedIds = [], prompt: promptProp, error = '',
    taskId, isMobile = false, onFullscreen,
  }: Props = $props();
  let currentCount = $state<number | undefined>(undefined);
  let currentError = $state<string | undefined>(undefined);
  let currentChildIds = $state<string[] | undefined>(undefined);
  let childPrompt = $state<string | undefined>(undefined);
  // Announced by the skill as soon as it starts: prompt, model and input images.
  let request = $state<GenerationRequestInfo>(EMPTY_GENERATION_REQUEST);
  const prompt = $derived(promptProp?.trim() || childPrompt || request.prompt || undefined);
  const skillName = $derived($text(`app_skills.${appId}.${skillId}`));
  // A change to an existing image pins that image's new version instead of listing a child.
  let pinnedIds = $state<string[]>([]);
  const childIds = $derived([...new Set([...(currentChildIds ?? childEmbedIds), ...pinnedIds])]);
  const count = $derived(Math.max(currentCount ?? 0, resultCount ?? 0, childIds.length));

  function handleUpdated(data: { decodedContent: Record<string, unknown> | null }) {
    const content = data.decodedContent;
    if (!content) return;
    currentCount = Math.max(
      typeof content.result_count === 'number' ? content.result_count : 0,
      generatedMediaChildIds(content).length,
    );
    currentError = typeof content.error === 'string' ? content.error : undefined;
    const ids = generatedMediaChildIds(content);
    if (ids.length > 0) currentChildIds = ids;
    void readPins(content);
  }

  async function readPins(content: Record<string, unknown>) {
    try {
      const pins = await pinnedEmbedsOf(content);
      if (pins.length === 0) return;
      // The final manifest lists only owned children: the draft placeholder is gone.
      currentChildIds = generatedMediaChildIds(content);
      pinnedIds = pins.map((pin) => pin.embed_id);
    } catch (pinError) {
      console.error('[GeneratedMediaGroupEmbedPreview] Pinned versions unreadable:', pinError);
      currentError = typeof (pinError as { code?: unknown })?.code === 'string' ? String((pinError as { code: string }).code) : 'embed_pins_unreadable';
    }
  }

  // A vector graphic is drawn live: its drafts arrive as processing updates of
  // the child image embed while this parent card is the one on screen. Until a
  // draft has something to look at, the card shows the request instead.
  let svgDraftState = $state<SvgDraftState>(EMPTY_SVG_DRAFT);
  const showSvgDraft = $derived(status === 'processing' && hasDrawableSvg(svgDraftState.draft));
  const showRequest = $derived(status === 'processing' && !showSvgDraft && !!prompt);
  const draftStageLabelKey = $derived(svgDraftStageLabelKey(svgDraftState.stage));
  const modelLabel = $derived(request.model ? imageGenerationAttribution(request.model) : undefined);
  const FADE_MS = 350;

  async function handleChildDraft(event: Event) {
    const toon = childDraftContent((event as CustomEvent).detail, id);
    if (!toon) return;
    const decoded = await decodeToonContent(toon) as Record<string, unknown> | null;
    if (!decoded) return;
    request = readGenerationRequest(decoded, request);
    svgDraftState = mergeSvgDraft(svgDraftState, readSvgDraft(decoded));
  }
  chatSyncService.addEventListener('embedUpdated', handleChildDraft);
  onDestroy(() => chatSyncService.removeEventListener('embedUpdated', handleChildDraft));
</script>

<UnifiedEmbedPreview
  {id} {appId} {skillId} skillIconName={appId === 'models3d' ? '3dmodels' : appId === 'design' ? 'embroidery' : appId}
  {status} {skillName} {taskId} {isMobile} {onFullscreen}
  onEmbedDataUpdated={handleUpdated}
  customStatusText={count > 0 ? `${count} · ${$text('apps_workspace.results')}` : undefined}
>
  {#snippet details()}
    <div class="generated-media-parent" data-testid="generated-media-parent-preview">
      {#if showSvgDraft || showRequest}
        <!-- Request and picture share one box so the picture can fade in over the fading text. -->
        <div class="working">
          {#if showSvgDraft}
            <div class="svg-draft" data-testid="image-generate-svg-draft" data-stage={svgDraftState.stage}
                 data-attempt={svgDraftState.attempt} in:fade={{ duration: FADE_MS }}>
              <SvgEmbedImage code={svgDraftState.draft} title={prompt || skillName} streaming={true} />
              {#if draftStageLabelKey}
                <span class="svg-draft-stage" data-testid="image-generate-svg-draft-stage">{$text(draftStageLabelKey)}</span>
              {/if}
            </div>
          {:else}
            <div class="request" data-testid="image-generate-request" data-stage={svgDraftState.stage}
                 out:fade={{ duration: FADE_MS }}>
              {#if request.inputEmbedIds.length > 0}
                <div class="request-input" data-testid="image-generate-request-input">
                  <GeneratedMediaThumbnails childEmbedIds={request.inputEmbedIds} />
                </div>
              {/if}
              <div class="request-text">
                <span class="request-model shimmer" data-testid="image-generate-request-model">
                  {draftStageLabelKey ? $text(draftStageLabelKey)
                    : modelLabel ? `${$text('embeds.image_generate.generating_via')} ${modelLabel}` : skillName}
                </span>
                <p class="request-prompt shimmer" data-testid="image-generate-request-prompt">{prompt}</p>
              </div>
            </div>
          {/if}
        </div>
      {:else if childIds.length > 0}
        <GeneratedMediaThumbnails childEmbedIds={childIds} onPrompt={(value) => { childPrompt = value; }} />
      {/if}
      {#if prompt && !showRequest}<p class="prompt" data-testid="generated-media-parent-prompt">{prompt}</p>{/if}
      {#if currentError || error}<span class="partial-error">{currentError || error}</span>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .generated-media-parent { display: flex; flex-direction: column; gap: var(--spacing-3); height: 100%; min-height: 0; box-sizing: border-box; padding: var(--spacing-3) 0 var(--spacing-6); color: var(--color-font-primary); }
  /* The first lines of the prompt that fit; the full prompt stays in fullscreen. */
  .prompt { margin: 0; flex: 0 0 auto; font-size: var(--font-size-sm); line-height: 1.3; color: var(--color-font-secondary); display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; overflow: hidden; overflow-wrap: anywhere; }
  .working { position: relative; flex: 1; min-height: 0; }
  .svg-draft { position: absolute; inset: 0; overflow: hidden; display: flex; align-items: center; justify-content: center; border-radius: var(--radius-2); background: var(--color-media-letterbox); }
  .svg-draft :global(.svg-embed-image) { width: 100%; height: 100%; }
  .svg-draft .svg-draft-stage { position: absolute; left: var(--spacing-4); bottom: var(--spacing-4); padding: var(--spacing-1) var(--spacing-4); border-radius: var(--radius-2); background: rgba(0, 0, 0, 0.55); color: #fff; pointer-events: none; }
  .svg-draft-stage { font-size: var(--font-size-tiny); line-height: 1.3; }
  /* The request shown until a picture exists: input image(s) beside the prompt. */
  .request { position: absolute; inset: 0; display: flex; align-items: stretch; gap: var(--spacing-4); overflow: hidden; }
  .request-input { flex: 0 0 38%; min-width: 0; display: flex; }
  .request-text { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: var(--spacing-2); overflow: hidden; }
  .request-model { flex: 0 0 auto; font-size: var(--font-size-tiny); line-height: 1.3; font-weight: 600; }
  .request-prompt { margin: 0; flex: 1 1 0; min-height: 0; font-size: var(--font-size-sm); line-height: 1.35; overflow: hidden; overflow-wrap: anywhere; }
  /* Same moving highlight as the processing status text in BasicInfosBar. */
  .shimmer { background: linear-gradient(90deg, var(--color-grey-70) 0%, var(--color-grey-70) 40%, var(--color-grey-50) 50%, var(--color-grey-70) 60%, var(--color-grey-70) 100%); background-size: 200% 100%; background-clip: text; -webkit-background-clip: text; color: transparent; animation: request-shimmer 1.5s infinite linear; }
  @keyframes request-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
  @media (prefers-reduced-motion: reduce) { .shimmer { animation: none; color: var(--color-font-secondary); background: none; } }
  .partial-error { color: var(--color-font-secondary); font-size: var(--font-size-sm); }
</style>
