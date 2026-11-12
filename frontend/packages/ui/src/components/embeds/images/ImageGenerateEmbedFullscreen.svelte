<!--
  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedFullscreen.svelte
  
  Fullscreen view for Image Generate embeds.
  Uses UnifiedEmbedFullscreen as base and provides image-specific content.
  
  Shows:
  - Full resolution decrypted image from S3
  - Prompt text
  - Model, aspect ratio, resolution metadata
  - Download button for original PNG
-->

<script lang="ts">
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  const sourceChatContext = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  const sourceChatId = sourceChatContext?.exampleChatId ?? sourceChatContext?.lookupChatId ?? sourceChatContext?.chatId ?? null;
  import { onDestroy, getContext, untrack } from 'svelte';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import { text, settingsDeepLink, panelState } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { fetchAndDecryptImage, getCachedImageUrl, createImageUrlOwner } from './imageEmbedCrypto';
  const { retain: retainCachedImage, release: releaseCachedImage, destroy: releaseOwnedImages } = createImageUrlOwner();

  import { generateImageFilename, embedPngMetadata } from './imageDownloadUtils';
  import { getModelByNameOrId } from '../../../utils/modelDisplayName';
  import { imageGenerationAttribution, imageGenerationFilename } from './imageGenerationMetadata';
  import { getProviderIconUrl } from '../../../data/providerIcons';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { resolveEmbed, decodeToonContent } from '../../../services/embedResolver';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
  import SvgEmbedImage from '../code/SvgEmbedImage.svelte';
  import ImageModifyProgress from './ImageModifyProgress.svelte';
  import ImageModifyUnmet from './ImageModifyUnmet.svelte';
  import { isModifySkill, readImageModify, readUnmetRequirements } from './imageDraft';
  import { readSvgDraft, shouldShowDraftStatusOnly, shouldShowSvgDraft, svgDraftStageLabelKey } from './svgDraft';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import { EMBED_VERSIONS_ENABLED, embedContentAtVersion, embedHead } from '../../../services/rustCore/embeds/messageEmbedVersion';
  import { takeFullscreenVersion, versionBadgeLabel } from './imageVersionScope';
  import { createImageEnhance, imageEditAvailability, imageEditErrorKey } from './imageEnhance.svelte';
  import { EMBED_EDITS_ENABLED, enhanceImage, restoreEmbedVersion, runningEnhance } from '../../../services/rustCore/embeds/embedEditSession';
  import { requestEmbedFromServerOnce } from '../../../services/embedResolver';
  import { noteEmbedHeadChanged } from '../../../services/rustCore/embeds/messageEmbedVersion';
  import { activeTeamId } from '../../../stores/teamStore';
  import { get } from 'svelte/store';

  /**
   * Type for files metadata from embed content
   */
  interface ImageFileVariant {
    s3_key: string;
    width: number;
    height: number;
    format: string;
    aes_nonce?: string;
    encryption?: string;
  }

  interface ImageFiles {
    preview?: ImageFileVariant;
    full?: ImageFileVariant;
    original?: ImageFileVariant;
  }

  /**
   * Props for image generate embed fullscreen
   */
  interface Props {
    /** Standardized raw embed data (decodedContent, attrs, embedData) */
    data: EmbedFullscreenRawData;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Direction of navigation ('previous' | 'next') — set transiently during prev/next transitions */
    navigateDirection?: 'previous' | 'next';
     /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
    /** Version to open at (the card's message version); defaults to the version the card remembered, else the head. */
    initialVersion?: number;
    /** Preview only: the version shown and the number of versions, without the core. */
    version?: number;
    versionCount?: number;
    /** Enhance button (presentation only; the caller runs the Enhance). Omit onEnhance to hide it. */
    onEnhance?: () => void;
    /** False shows the button disabled with a reason (viewer without edit rights). Default true. */
    canEnhance?: boolean;
    enhanceState?: 'idle' | 'running' | 'failed';
    /** Message of a failed Enhance; shown as a notification and as the button tooltip. */
    enhanceError?: string;
    /** Opened from the Projects workspace: Enhance and restore save in this Project. */
    projectId?: string;
    teamId?: string | null;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    initialVersion,
    version: previewVersion,
    versionCount,
    onEnhance,
    canEnhance = true,
    enhanceState = 'idle',
    enhanceError,
    projectId,
    teamId,
  }: Props = $props();

  // ── Extract fields from data.decodedContent and data.embedData ──────────────

  // Image versions (`images-generate.revision.message-shows-its-version`): the fullscreen
  // opens at the version of the message it came from; the timeline switches versions.
  // Read once on open (on purpose): later version changes come from the timeline.
  const startVersion = untrack(() => initialVersion ?? previewVersion ?? takeFullscreenVersion(embedId));
  let headVersion = $state<number | undefined>(untrack(() => versionCount));
  let shownVersion = $state<number | undefined>(startVersion);
  let versionContent = $state<Record<string, unknown> | null>(null);
  let versionError = $state<string | undefined>(undefined);
  let versionBadge = $derived(versionBadgeLabel(shownVersion ?? headVersion, headVersion));

  let dc = $derived(versionContent ?? data.decodedContent);
  let ed = $derived(data.embedData);
  let prompt = $derived(typeof dc.prompt === 'string' ? dc.prompt : undefined);
  let model = $derived(typeof dc.model === 'string' ? dc.model : undefined);
  let provider = $derived(typeof dc.provider === 'string' ? dc.provider : undefined);
  let filename = $derived(imageGenerationFilename(dc, embedId));
  let aspectRatio = $derived(typeof dc.aspect_ratio === 'string' ? dc.aspect_ratio : undefined);
  let s3BaseUrl = $derived(typeof dc.s3_base_url === 'string' ? dc.s3_base_url : undefined);
  let files = $derived((typeof dc.files === 'object' && dc.files !== null) ? dc.files as ImageFiles : undefined);
  let aesKey = $derived(typeof dc.aes_key === 'string' ? dc.aes_key : undefined);
  let aesNonce = $derived(typeof dc.aes_nonce === 'string' ? dc.aes_nonce : undefined);
  let status = $derived(typeof ed?.status === 'string' ? ed.status : 'finished');
  let error = $derived(typeof dc.error === 'string' ? dc.error : undefined);
  // Live SVG drawing while the vector author is still working
  let svgDraftState = $derived(readSvgDraft(dc));
  let showSvgDraft = $derived(shouldShowSvgDraft(status, svgDraftState.draft));
  let showDraftStatusOnly = $derived(shouldShowDraftStatusOnly(status, svgDraftState.draft, svgDraftState.stage));
  let draftStageLabelKey = $derived(svgDraftStageLabelKey(svgDraftState.stage));
  let skillIdProp = $derived<'generate' | 'generate_draft' | 'modify'>(
    typeof dc.skill_id === 'string' && dc.skill_id === 'generate_draft' ? 'generate_draft'
      : isModifySkill(dc.skill_id) ? 'modify' : 'generate');
  // images.modify progress and review result
  let modifyState = $derived(readImageModify(dc));
  let showModifyProgress = $derived(isModifySkill(skillIdProp) && status === 'processing' && (!!modifyState.stage || !!modifyState.draft));
  let unmetRequirements = $derived(readUnmetRequirements(dc));
  let generatedAt = $derived(typeof dc.generated_at === 'string' ? dc.generated_at : undefined);
  let inputEmbedIds = $derived(Array.isArray(dc.input_embed_ids) ? dc.input_embed_ids as string[] : undefined);
  // Direct preview image URL for store examples — bypasses S3 decrypt
  let directPreviewImageUrl = $derived(typeof dc.previewImageUrl === 'string' ? dc.previewImageUrl : undefined);

  // Image state
  // Progressive loading: show the preview image instantly while the full-res version loads.
  // The preview is typically already cached from the inline embed, so it appears immediately.
  let previewImageUrl = $state<string | undefined>(undefined);
  let fullImageUrl = $state<string | undefined>(undefined);
  let isLoadingImage = $state(false);
  let imageError = $state<string | undefined>(undefined);
  let isDownloading = $state(false);
  
  // Track retained S3 keys for cleanup
  let retainedPreviewKey: string | undefined = undefined;
  let retainedFullKey: string | undefined = undefined;

  // Input (reference) image thumbnails — keyed by embed ID
  let inputImageUrls = $state<Map<string, string>>(new Map());
  // Decoded TOON content per input embed (needed to open fullscreen on click)
  let inputEmbedContents = $state<Map<string, Record<string, unknown>>>(new Map());
  let retainedInputKeys: string[] = [];
  
  const skillIconName = 'ai';

  // The header and download use the same saved asset name.
  let embedHeaderTitle = $derived(filename || (skillIdProp === 'generate_draft'
    ? $text('embeds.image_generate_draft') : skillIdProp === 'modify' ? $text('embeds.image_modify.title') : $text('common.generate')));

  // Header subtitle: skill display name (doubles as "Generated image" label)
  let embedHeaderSubtitle = $derived(
    skillIdProp === 'generate_draft'
      ? $text('embeds.image_generate_draft')
      : skillIdProp === 'modify' ? $text('embeds.image_modify.title') : $text('common.generate')
  );
  
  let modelMetadata = $derived(model ? getModelByNameOrId(model) : undefined);
  let modelDisplayName = $derived(imageGenerationAttribution(model, provider));

  // Provider icon URL resolved from metadata logo_svg field
  let providerIconUrl = $derived(
    modelMetadata?.logo_svg ? getProviderIconUrl(modelMetadata.logo_svg) : undefined
  );
  
  // Track copy feedback state
  let showCopied = $state(false);
  
  /** Drop the shown picture so the image effect loads the selected version's files. */
  function resetImage() {
    if (retainedPreviewKey) releaseCachedImage(retainedPreviewKey);
    if (retainedFullKey) releaseCachedImage(retainedFullKey);
    retainedPreviewKey = undefined;
    retainedFullKey = undefined;
    previewImageUrl = undefined;
    fullImageUrl = undefined;
    imageError = undefined;
  }

  /** Show version `version`: `toon` is its plaintext, null for the stored head. */
  async function showVersion(version: number, toon: string | null) {
    versionError = undefined;
    const content = toon === null ? null : await decodeToonContent(toon);
    if (toon !== null && !content) {
      versionError = 'embed_version_content_undecodable';
      return;
    }
    resetImage();
    shownVersion = version;
    versionContent = (content as Record<string, unknown> | null) ?? null;
  }

  function versionChatId(): string {
    if (!sourceChatId) throw new Error('embed_version_chat_unknown');
    return sourceChatId;
  }

  $effect(() => {
    if (!EMBED_VERSIONS_ENABLED || !embedId || versionCount !== undefined) return;
    const id = embedId;
    void (async () => {
      try {
        const head = await embedHead(id);
        headVersion = head?.version ?? 1;
        if (startVersion && startVersion < headVersion) {
          await showVersion(startVersion, await embedContentAtVersion(versionChatId(), id, startVersion));
        } else {
          shownVersion = headVersion;
        }
      } catch (err) {
        console.error('[ImageGenerateEmbedFullscreen] Failed to open the image version:', err);
        versionError = err instanceof Error ? err.message : String(err);
      }
    })();
  });

  /**
   * Load the full-resolution image from S3 with progressive enhancement.
   * 1. Instantly show the cached preview (likely already decrypted by the inline preview)
   * 2. Fetch + decrypt the full-resolution image in the background
   * 3. Swap to full-res when ready
   */
  async function loadFullImage() {
    if (!s3BaseUrl || !aesKey) return;
    if (fullImageUrl) return;
    
    // Step 1: Show cached preview instantly for progressive loading
    const previewKey = files?.preview?.s3_key;
    if (previewKey && !previewImageUrl) {
      const cachedPreview = getCachedImageUrl(previewKey);
      if (cachedPreview) {
        previewImageUrl = cachedPreview;
        retainedPreviewKey = previewKey;
        retainCachedImage(previewKey);
      }
    }
    
    // Step 2: Load the full-res version
    const fullFileData = files?.full || files?.preview;
    if (!fullFileData?.s3_key || !hasMediaEncryptionMetadata(fullFileData, aesNonce)) return;
    
    // Check cache for full-res too
    const cachedFull = getCachedImageUrl(fullFileData.s3_key);
    if (cachedFull) {
      fullImageUrl = cachedFull;
      retainedFullKey = fullFileData.s3_key;
      retainCachedImage(fullFileData.s3_key);
      return;
    }
    
    isLoadingImage = true;
    imageError = undefined;
    
    try {
      console.debug('[ImageGenerateEmbedFullscreen] Loading full image from S3:', fullFileData.s3_key);
      await fetchAndDecryptImage(s3BaseUrl, fullFileData.s3_key, aesKey, aesNonce ?? '', fullFileData);
      fullImageUrl = getCachedImageUrl(fullFileData.s3_key)!;
      retainedFullKey = fullFileData.s3_key;
      retainCachedImage(fullFileData.s3_key);
    } catch (err) {
      console.error('[ImageGenerateEmbedFullscreen] Failed to load full image:', err);
      imageError = err instanceof Error ? err.message : 'Failed to load image';
    } finally {
      isLoadingImage = false;
    }
  }
  
  // Auto-load full image on mount.
  // Store examples provide a direct URL — skip S3 decrypt entirely.
  $effect(() => {
    if (status === 'finished' && !fullImageUrl && !isLoadingImage) {
      if (directPreviewImageUrl) {
        fullImageUrl = directPreviewImageUrl;
      } else {
        loadFullImage();
      }
    }
  });
  
  // Cleanup: release cached image references on unmount
  onDestroy(() => {
    releaseOwnedImages();
    if (retainedPreviewKey) releaseCachedImage(retainedPreviewKey);
    if (retainedFullKey) releaseCachedImage(retainedFullKey);
    for (const key of retainedInputKeys) {
      releaseCachedImage(key);
    }
    retainedInputKeys = [];
  });
  
  /**
   * Load and decrypt preview thumbnails for input (reference) images.
   * Also caches the decoded TOON content so we can open the correct
   * ImageEmbedFullscreen when the user clicks a thumbnail.
   */
  async function loadInputImages(embedIds: string[]) {
    for (const embedId of embedIds) {
      if (inputImageUrls.has(embedId)) continue;

      try {
        const embedData = await resolveEmbed(embedId, { chatId: sourceChatId });
        if (!embedData?.content) continue;

        const content = await decodeToonContent(embedData.content);
        if (!content) continue;

        // Store decoded content for use in the click handler
        inputEmbedContents = new Map(inputEmbedContents).set(embedId, content as Record<string, unknown>);

        const inputS3BaseUrl = content.s3_base_url as string | undefined;
        const inputFiles = content.files as Record<string, { s3_key: string; aes_nonce?: string; encryption?: string }> | undefined;
        const inputAesKey = content.aes_key as string | undefined;
        const inputAesNonce = content.aes_nonce as string | undefined;

        const previewFile = inputFiles?.preview;
        const previewKey = previewFile?.s3_key;
        if (!previewKey || !inputS3BaseUrl || !inputAesKey || !hasMediaEncryptionMetadata(previewFile, inputAesNonce)) continue;

        const cached = getCachedImageUrl(previewKey);
        if (cached) {
          retainCachedImage(previewKey);
          retainedInputKeys.push(previewKey);
          inputImageUrls = new Map(inputImageUrls).set(embedId, cached);
          continue;
        }

        await fetchAndDecryptImage(inputS3BaseUrl, previewKey, inputAesKey, inputAesNonce ?? '', previewFile);
        const url = getCachedImageUrl(previewKey)!;
        retainCachedImage(previewKey);
        retainedInputKeys.push(previewKey);
        inputImageUrls = new Map(inputImageUrls).set(embedId, url);
      } catch (err) {
        console.warn('[ImageGenerateEmbedFullscreen] Failed to load input image thumbnail:', embedId, err);
      }
    }
  }

  // Auto-load input image thumbnails on mount
  $effect(() => {
    if (inputEmbedIds && inputEmbedIds.length > 0) {
      loadInputImages(inputEmbedIds);
    }
  });

  /**
   * Open a reference input image in the ImageEmbedFullscreen viewer by
   * dispatching the same `imagefullscreen` CustomEvent used elsewhere.
   */
  function handleInputImageClick(embedId: string) {
    const content = inputEmbedContents.get(embedId);
    if (!content) return;
    const event = new CustomEvent('imagefullscreen', {
      detail: {
        src: undefined,
        filename: (content.filename as string) || '',
        s3Files: content.files,
        s3BaseUrl: (content.s3_base_url as string) || '',
        aesKey: (content.aes_key as string) || '',
        aesNonce: (content.aes_nonce as string) || '',
        isAuthenticated: true,
        fileSize: content.file_size,
        fileType: content.file_type,
        aiDetection: (content.ai_detection as {
          ai_generated: number;
          provider: string;
          status?: 'success' | 'failed';
          error?: string | null;
        } | null) ?? null,
      },
      bubbles: true,
    });
    document.dispatchEvent(event);
  }

  /**
   * Download the original PNG image with a prompt-based filename and
   * embedded PNG tEXt metadata (prompt, model, software).
   * The backend already injects XMP metadata before encryption; the tEXt
   * chunks we add here provide an additional layer that is more widely
   * visible in file managers (macOS Finder, Windows Explorer, etc.).
   */
  async function handleDownload() {
    if (!files?.original?.s3_key || !s3BaseUrl || !aesKey || !hasMediaEncryptionMetadata(files.original, aesNonce)) return;
    if (isDownloading) return;
    
    isDownloading = true;
    
    try {
      const blob = await fetchAndDecryptImage(s3BaseUrl, files.original.s3_key, aesKey, aesNonce ?? '', files.original);
      const ext = files.original.format || 'png';
      
      // Embed PNG tEXt metadata (prompt, model, software) into the image bytes.
      // This makes the metadata visible in macOS Finder, Preview, and other viewers.
      let downloadBlob: Blob = blob;
      if (ext === 'png') {
        const arrayBuffer = await blob.arrayBuffer();
        const metadataBytes = embedPngMetadata(arrayBuffer, {
          prompt,
          model,
          software: 'OpenMates',
          generatedAt
        });
        // Copy into a plain ArrayBuffer to satisfy BlobPart typing
        const ab = new ArrayBuffer(metadataBytes.byteLength);
        new Uint8Array(ab).set(metadataBytes);
        downloadBlob = new Blob([ab], { type: 'image/png' });
      }
      
      // Generate a human-readable filename from the prompt
      const downloadFilename = filename || generateImageFilename(prompt, ext);
      
      // Create download link
      const url = URL.createObjectURL(downloadBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadFilename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('[ImageGenerateEmbedFullscreen] Failed to download original:', err);
    } finally {
      isDownloading = false;
    }
  }
  
  /**
   * Copy the prompt text to clipboard
   */
  async function handleCopyPrompt() {
    if (!prompt) return;
    try {
      const clipResult = await copyToClipboard(prompt);
      if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      showCopied = true;
      setTimeout(() => { showCopied = false; }, 1500);
    } catch (err) {
      console.error('[ImageGenerateEmbedFullscreen] Failed to copy prompt:', err);
    }
  }
  
  /**
   * Navigate to the images app skill settings page in Apps.
   * Deep links to the skill page for the current skill (generate or generate_draft).
   */
  function handleModelClick() {
    const skillPath = skillIdProp === 'generate_draft' ? 'generate_draft' : 'generate';
    settingsDeepLink.set(`apps/images/skill/${skillPath}`);
    panelState.openSettings();
  }

  // Enhance and restore through the client core (embed-user-edits); the preview passes its own onEnhance.
  let chatTeamId = $state<string | null | undefined>(undefined);
  $effect(() => {
    const chatId = sourceChatContext?.chatId;
    if (!EMBED_EDITS_ENABLED || projectId || !chatId) { chatTeamId = null; return; }
    void import('../../../services/db').then(({ chatDB }) => chatDB.getChat(chatId))
      .then((chat) => { chatTeamId = chat?.team_id ?? get(activeTeamId) ?? null; })
      .catch((err: unknown) => { console.error('[ImageGenerateEmbedFullscreen] Chat of the image unreadable:', err); chatTeamId = null; });
  });
  let editPlace = $derived(chatTeamId === undefined ? null : imageEditAvailability({
    chatId: sourceChatContext?.chatId ?? null, chatTeamId, projectId, projectTeamId: teamId,
    readOnly: sourceChatContext?.isReadOnly === true || !!sourceChatContext?.exampleChatId,
  }));
  let coreEditable = $derived(EMBED_EDITS_ENABLED && !!embedId && !onEnhance && status === 'finished' && !!files);
  let editScope = $derived(editPlace?.kind === 'available' ? editPlace.scope : null);

  /** After a save: load the new head from the server so this view and the chat card show it. */
  async function reloadHead(version: number | null) {
    if (!embedId) return;
    await requestEmbedFromServerOnce(embedId, 'user embed version saved', { chatId: projectId ? null : sourceChatId });
    noteEmbedHeadChanged(embedId);
    const head = await embedHead(embedId);
    headVersion = head?.version ?? version ?? headVersion;
    const stored = await resolveEmbed(embedId, { chatId: projectId ? null : sourceChatId });
    if (typeof stored?.content === 'string' && headVersion !== undefined) await showVersion(headVersion, stored.content);
  }
  const coreEnhance = createImageEnhance(() => embedId, () => editScope, {
    enhance: enhanceImage, running: runningEnhance, translate: (key) => $text(key), reloadHead,
  });
  $effect(() => { if (coreEditable && editScope) void untrack(() => coreEnhance.resume()); });

  async function restoreVersion(restoredContent: string, selected: number): Promise<{ version: number; content: string }> {
    if (!embedId || !editScope) throw new Error($text('embed_user_edits.restore_failed'));
    try {
      const restored = await restoreEmbedVersion(embedId, editScope, selected);
      await reloadHead(restored.version);
      return { version: restored.version, content: restoredContent };
    } catch (err) {
      const code = (err as { code?: unknown } | null)?.code;
      if (code === 'embed_version_conflict') await reloadHead(null);
      throw new Error($text(imageEditErrorKey(typeof code === 'string' ? code : undefined, 'restore')));
    }
  }

  let shownEnhance = $derived(coreEditable && editPlace ? {
    onEnhance: coreEnhance.start,
    state: editScope ? coreEnhance.state : 'unavailable' as const,
    error: coreEnhance.error,
    reason: $text(editPlace.kind === 'unavailable' && editPlace.reason === 'team'
      ? 'embed_user_edits.enhance_unavailable_team' : 'embed_user_edits.enhance_unavailable'),
  } : null);

  let notifiedEnhanceError: string | undefined;
  $effect(() => {
    const failed = (shownEnhance?.state ?? enhanceState) === 'failed'
      ? (shownEnhance?.error ?? enhanceError ?? $text('embed_user_edits.enhance_failed')) : undefined;
    if (failed && failed !== notifiedEnhanceError) notificationStore.error(failed);
    notifiedEnhanceError = failed;
  });

  /**
   * Open the shown image by itself in a new tab. The tab must open inside the tap
   * itself: waiting for a download or decryption first makes mobile browsers block
   * the popup, and re-decrypting the original per tap is heavy. The browser's own
   * zoom then works on the image, so no in-app zoom is needed.
   * Middle-click and Ctrl/Cmd+click use the native link.
   */
  function handleImageClick(e: MouseEvent) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    if (fullImageUrl) window.open(fullImageUrl, '_blank', 'noopener,noreferrer');
  }
</script>

<ResultEmbedFullscreen
  result={{ filename, prompt, model, provider, aspect_ratio: aspectRatio, generated_at: generatedAt }}
  mediaLayout="immersive"
  appId="images"
  skillId={skillIdProp}
  {skillIconName}
  embedHeaderTitle={embedHeaderTitle}
  embedHeaderSubtitle={embedHeaderSubtitle}
  showSkillIcon={true}
  {onClose}
  onDownload={files?.original ? handleDownload : undefined}
  onEnhance={shownEnhance?.onEnhance ?? onEnhance}
  enhanceState={shownEnhance?.state ?? (canEnhance ? enhanceState : 'unavailable')}
  enhanceError={shownEnhance?.error ?? enhanceError ?? $text('embed_user_edits.enhance_failed')}
  enhanceUnavailableReason={shownEnhance?.reason ?? $text('embed_user_edits.enhance_unavailable')}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet summary()}
    {#if aspectRatio}<ResultEmbedInfo icon="ratio" label={aspectRatio} value={aspectRatio} />{/if}
  {/snippet}
  {#snippet media()}
    <div class="image-fullscreen">
      {#if error}
        <!-- Error state -->
        <div class="error-container">
          <div class="error-icon">!</div>
          <h3 class="error-title">{$text('embeds.image_generate.error')}</h3>
          <p class="error-message">{error}</p>
        </div>
      {:else}
        <!-- Image display with progressive loading:
             1. Show cached preview instantly (blurred) while full-res loads
             2. Swap to full-res when ready
             On desktop this sits on the right; on narrow containers it appears first (top via CSS order). -->
        <div class="image-section">
          {#if showModifyProgress}
            <div class="svg-draft" data-testid="image-modify-opened">
              <ImageModifyProgress state={modifyState} title={prompt || filename} fit="contain" />
            </div>
          {:else if showSvgDraft}
            <div
              class="svg-draft"
              data-testid="image-generate-svg-draft"
              data-stage={svgDraftState.stage}
              data-attempt={svgDraftState.attempt}
            >
              <SvgEmbedImage code={svgDraftState.draft} title={prompt || filename} streaming={true} />
              {#if draftStageLabelKey}
                <span class="svg-draft-stage" data-testid="image-generate-svg-draft-stage">{$text(draftStageLabelKey)}</span>
              {/if}
            </div>
          {:else if showDraftStatusOnly && draftStageLabelKey}
            <div class="svg-draft draft-status" data-testid="image-generate-draft-status" data-stage={svgDraftState.stage}>
              <span class="svg-draft-stage" data-testid="image-generate-svg-draft-stage">{$text(draftStageLabelKey)}</span>
            </div>
          {:else if versionError}
            <div class="error-container" data-testid="image-generate-version-error">
              <div class="error-icon">!</div>
              <p class="error-message">{versionError}</p>
            </div>
          {:else if fullImageUrl}
            <div class="image-wrapper" data-embed-version={shownVersion ?? 1}>
              <a href={fullImageUrl} target="_blank" rel="noopener noreferrer" class="image-link" title={$text('embeds.image_generate.open_full_size')} onclick={handleImageClick}>
                <img src={fullImageUrl} alt={prompt || 'Generated image'} class="result-primary-media full-image" data-embed-version={shownVersion ?? 1} />
              </a>
              {#if versionBadge}
                <span class="version-badge" data-testid="image-generate-version-badge">{versionBadge}</span>
              {/if}
            </div>
          {:else if previewImageUrl && isLoadingImage}
            <!-- Progressive: show preview while full-res loads -->
            <div class="image-wrapper progressive">
              <img src={previewImageUrl} alt={prompt || 'Generated image'} class="result-primary-media full-image preview-placeholder" />
              <div class="progressive-overlay">
                <div class="loading-spinner small"></div>
              </div>
            </div>
          {:else if isLoadingImage}
            <div class="image-loading">
              <div class="loading-spinner"></div>
              <span class="loading-text">{$text('embeds.image_generate.loading')}</span>
            </div>
          {:else if imageError}
            <div class="error-container">
              <div class="error-icon">!</div>
              <p class="error-message">{imageError}</p>
            </div>
          {/if}
        </div>
        {#if embedId && headVersion && headVersion > 1}
          <EmbedVersionTimeline
            {embedId}
            chatId={sourceChatId ?? undefined}
            currentVersion={headVersion}
            currentContent=""
            initialVersion={shownVersion}
            showChangesToggle={false}
            loadVersionContent={(version) => embedContentAtVersion(versionChatId(), embedId, version)}
            onVersionSelect={(version, content) => { void showVersion(version, content); }}
            onVersionError={(version) => { versionError = `embed_version_unavailable:v${version}`; }}
            onRestoreVersion={coreEditable && editScope ? restoreVersion : undefined}
          />
        {/if}
      {/if}
    </div>
  {/snippet}
  {#snippet detailContent()}
    {#if !error}
        <!-- Prompt area: "Generated by" line + quote card with prompt text.
             On desktop (wide containers) this sits on the left; on narrow containers it goes below the image. -->
        <div class="prompt-area">
          <!-- Input reference image thumbnails — shown when image-to-image generation was used -->
          {#if inputEmbedIds && inputEmbedIds.length > 0}
            <div class="input-images-row">
              {#each inputEmbedIds as embedId (embedId)}
                {@const thumbUrl = inputImageUrls.get(embedId)}
                <button
                  class="input-thumb-btn"
                  onclick={() => handleInputImageClick(embedId)}
                  title="View input image"
                  aria-label="View input image"
                >
                  {#if thumbUrl}
                    <img src={thumbUrl} alt="" class="input-thumb-img" />
                  {:else}
                    <div class="input-thumb-placeholder"></div>
                  {/if}
                </button>
              {/each}
            </div>
          {/if}

          <!-- "Generated by {Model}" line with provider icon - clickable to open images skill settings -->
          {#if modelDisplayName && skillIdProp !== 'modify'}
            <button class="generated-by-line" onclick={handleModelClick}>
              {#if providerIconUrl}
                <img src={providerIconUrl} alt="" class="provider-icon" />
              {/if}
              <span class="generated-by-text">
                {$text('embeds.image_generate.generated_by')} {modelDisplayName}
              </span>
            </button>
          {/if}
          
          {#if unmetRequirements.length > 0}
            <ImageModifyUnmet requirements={unmetRequirements} />
          {/if}

          <!-- Prompt quote card with decorative quote icons -->
          {#if prompt}
            <div class="quote-card">
              <!-- Opening quote icon (bottom-left) -->
              <div class="quote-icon quote-open clickable-icon icon_quote"></div>
              
              <!-- Closing quote icon (top-right, rotated 180deg) -->
              <div class="quote-icon quote-close clickable-icon icon_quote"></div>
              
              <p class="prompt-text">{prompt}</p>
              
              <!-- Copy prompt button (bottom-right) -->
              <button
                class="copy-prompt-btn"
                onclick={handleCopyPrompt}
                title={showCopied ? 'Copied!' : 'Copy prompt'}
                aria-label="Copy prompt"
              >
                <span class="clickable-icon icon_copy copy-icon"></span>
              </button>
            </div>
          {/if}
        </div>
    {/if}
  {/snippet}
</ResultEmbedFullscreen>

<style>

  .image-section { width: 100%; box-sizing: border-box; }
  /* ===========================================
     Main Layout Container
     Wide containers: side-by-side (image left, prompt right)
     Narrow containers: stacked (image top, prompt below)
     Uses @container queries (not @media) for responsive layout
     since the fullscreen panel width depends on context, not viewport.
     =========================================== */
  
  .image-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: auto;
    overflow: auto;
    align-items: center;
    gap: 0;
  }
  
  /* ===========================================
     Image Section (left on wide, top on narrow)
     =========================================== */
  
  .image-section {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 0;
    min-width: 0;
    padding: 0;
  }
  
  .image-wrapper {
    position: relative;
    width: 100%;
    max-width: 100%;
    max-height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  /* Version of the picture when the image has more than one */
  .version-badge {
    position: absolute;
    top: var(--spacing-4);
    right: var(--spacing-4);
    padding: var(--spacing-1) var(--spacing-3);
    border-radius: var(--radius-2);
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    font-size: var(--font-size-tiny);
    font-weight: 600;
    line-height: 1.3;
    pointer-events: none;
  }

  /* Clickable link wrapper for the image - opens full size in new tab */
  .image-link {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    max-width: 100%;
    max-height: 100%;
    cursor: pointer;
  }
  
  .full-image {
    width: 100%;
    height: auto;
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: var(--radius-4);
    box-shadow: 0px 4px 4px 0px rgba(0, 0, 0, 0.25);
  }
  
  /* Progressive loading: show blurred preview while full-res loads */
  .image-wrapper.progressive {
    position: relative;
  }
  
  .preview-placeholder {
    filter: blur(2px);
    transition: filter var(--duration-slow) var(--easing-default);
  }
  
  .progressive-overlay {
    position: absolute;
    top: 12px;
    right: 12px;
    background: rgba(0, 0, 0, 0.4);
    border-radius: 50%;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .loading-spinner.small {
    width: 18px;
    height: 18px;
    border-width: 2px;
  }
  
  /* ===========================================
     Prompt Area (right on wide, below image on narrow)
     Contains "Generated by" line and quote card.
     Vertically centered alongside the image on wide layouts.
     =========================================== */
  
  .prompt-area {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    padding: 0;
    width: 100%;
    box-sizing: border-box;
    align-self: center;
    max-width: 100%;
    flex-shrink: 0;
  }
  
  /* ===========================================
     Input reference image thumbnails
     =========================================== */

  .input-images-row {
    display: flex;
    flex-direction: row;
    gap: var(--spacing-3);
    flex-wrap: wrap;
  }

  .input-thumb-btn {
    width: 48px;
    height: 48px;
    padding: 0;
    border: 2px solid var(--color-grey-20, #e0e0e0);
    border-radius: var(--radius-3);
    overflow: hidden;
    cursor: pointer;
    flex-shrink: 0;
    background: var(--color-grey-10, #f5f5f5);
    transition: border-color var(--duration-fast) var(--easing-default), transform var(--duration-fast) var(--easing-default);
  }

  .input-thumb-btn:hover {
    border-color: var(--color-primary-50, #5b8dd9);
    transform: scale(1.05);
  }

  .input-thumb-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .input-thumb-placeholder {
    width: 100%;
    height: 100%;
    background: var(--color-grey-20, #f0f0f0);
    animation: pulse 1.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  /* "Generated by {Model}" line with provider icon - clickable to open model settings.
     Simple text button, no background pill. Uses cursor:pointer and subtle hover. */
  .generated-by-line {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    padding: 0;
    background: none;
    border: none;
    cursor: pointer;
    align-self: flex-start;
  }
  
  .generated-by-line:hover .generated-by-text {
    text-decoration: underline;
  }
  
  .provider-icon {
    width: 19px;
    height: 19px;
    flex-shrink: 0;
  }
  
  .generated-by-text {
    font-family: 'Lexend Deca', sans-serif;
    font-size: var(--font-size-small);
    font-weight: 500;
    line-height: 1.25;
    color: var(--color-grey-60, #666);
  }
  
  /* ===========================================
     Quote Card - prompt text with decorative quotes
     White rounded card (30px radius).
     Prompt text uses a darker grey for better readability.
     =========================================== */
  
  .quote-card {
    position: relative;
    background-color: var(--color-grey-0, #ffffff);
    border-radius: 30px;
    padding: 24px 50px;
    min-height: 80px;
  }
  
  /* Quote icons - uses CSS mask with quote.svg from icons system */
  .quote-icon {
    position: absolute;
    width: 20px;
    height: 20px;
    background: var(--color-grey-100, #000) !important;
    cursor: default;
  }
  
  .quote-open {
    left: 12px;
    bottom: 12px;
  }
  
  .quote-close {
    right: 12px;
    top: 12px;
    transform: rotate(180deg);
  }
  
  /* Prompt text - darker color (#3A3A3A) for better visibility */
  .prompt-text {
    font-family: 'Lexend Deca', sans-serif;
    font-size: var(--font-size-p);
    font-weight: 500;
    line-height: 1.25;
    color: var(--color-grey-80, #3A3A3A);
    margin: 0;
    word-break: break-word;
    white-space: pre-wrap;
  }
  
  /* Copy prompt button - bottom-right corner of quote card */
  .copy-prompt-btn {
    position: absolute;
    right: 12px;
    bottom: 12px;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.5;
    transition: opacity var(--duration-normal) var(--easing-default);
  }
  
  .copy-prompt-btn:hover {
    opacity: 1;
  }
  
  .copy-icon {
    width: 19px;
    height: 19px;
    background: var(--color-primary-50, #5b8dd9) !important;
  }
  
  /* ===========================================
     Loading State
     =========================================== */
  
  .image-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-6);
    padding: var(--spacing-20);
  }
  
  .loading-spinner {
    width: 32px;
    height: 32px;
    border: 3px solid var(--color-grey-20, #eaeaea);
    border-top-color: var(--color-primary-50, #5b8dd9);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  
  .loading-text {
    font-size: var(--font-size-small);
    color: var(--color-grey-50, #888);
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  
  /* ===========================================
     Error State
     =========================================== */
  
  .error-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    text-align: center;
    padding: var(--spacing-16);
  }
  
  .error-icon {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--color-error-20, #f5c0c0);
    color: var(--color-error-70, #b04a4a);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--font-size-h2-mobile);
    font-weight: 700;
    margin-bottom: var(--spacing-8);
  }
  
  .error-title {
    font-size: var(--font-size-h3-mobile);
    font-weight: 600;
    margin: 0 0 8px 0;
    color: var(--color-grey-90, #1a1a1a);
  }
  
  .error-message {
    font-size: var(--font-size-small);
    color: var(--color-grey-60, #666);
    margin: 0;
    max-width: 400px;
  }
  
  /* ===========================================
     Dark Mode
     =========================================== */
  
  :global(.dark) .input-thumb-btn {
    border-color: var(--color-grey-70, #444);
    background: var(--color-grey-80, #2a2a2a);
  }

  :global(.dark) .input-thumb-btn:hover {
    border-color: var(--color-primary-40, #7a9ed0);
  }

  :global(.dark) .input-thumb-placeholder {
    background: var(--color-grey-70, #333);
  }

  :global(.dark) .quote-card {
    background-color: var(--color-grey-90, #1a1a1a);
  }
  
  :global(.dark) .quote-icon {
    background: var(--color-grey-0, #fff) !important;
  }
  
  :global(.dark) .prompt-text {
    color: var(--color-grey-20, #ddd);
  }
  
  :global(.dark) .generated-by-text {
    color: var(--color-grey-40, #999);
  }
  
  :global(.dark) .copy-icon {
    background: var(--color-primary-40, #7a9ed0) !important;
  }
  
  :global(.dark) .full-image {
    box-shadow: 0px 4px 4px 0px rgba(0, 0, 0, 0.5);
  }
  
  :global(.dark) .loading-spinner {
    border-color: var(--color-grey-70, #555);
    border-top-color: var(--color-primary-40, #7a9ed0);
  }
  
  :global(.dark) .loading-text {
    color: var(--color-grey-50, #888);
  }
  
  :global(.dark) .error-title {
    color: var(--color-grey-10, #f5f5f5);
  }
  
  :global(.dark) .error-message {
    color: var(--color-grey-40, #999);
  }
  
  /* ===========================================
     Responsive: Narrow container layout (stacked, image on top)
     Uses @container queries referencing the "fullscreen" container
     defined in UnifiedEmbedFullscreen, so layout adapts to the
     panel width, not the viewport width.
     =========================================== */
  
  @container fullscreen (max-width: 600px) {
    .image-fullscreen {
      flex-direction: column;
      align-items: stretch;
      overflow-y: auto;
      overflow-x: hidden;
    }
    
    /* On narrow: image appears first (top), prompt area below */
    .image-section {
      order: 1;
      flex: none;
      padding: 0;
      width: 100%;
    }
    
    /* Ensure the image fits the container width without horizontal scroll */
    .full-image {
      max-width: 100%;
      width: 100%;
      height: auto;
      max-height: none;
    }
    
    .prompt-area {
      order: 2;
      align-self: stretch;
      max-width: none;
      padding: 0 16px 16px 16px;
    }
    
    .quote-card {
      padding: 20px 46px;
    }
  }

  .svg-draft {
    position: relative;
    width: 100%;
    min-height: 240px;
    aspect-ratio: 1 / 1;
    max-height: 100%;
    overflow: hidden;
    border-radius: var(--radius-3);
  }

  .svg-draft-stage {
    position: absolute;
    left: var(--spacing-4);
    bottom: var(--spacing-4);
    padding: var(--spacing-1) var(--spacing-4);
    border-radius: var(--radius-2);
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    font-size: var(--font-size-tiny);
    pointer-events: none;
  }
</style>
