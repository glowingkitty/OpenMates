<!-- Shared result-detail structure; specialized editors retain their own layout. -->
<script lang="ts">
  import { getContext, onDestroy, type Snippet, type ComponentProps } from "svelte";
  import { get } from "svelte/store";
  import UnifiedEmbedFullscreen from "./UnifiedEmbedFullscreen.svelte";
  import EmbedLeafletMap, { type MapMarker, type MapPathPoint, type MapRoutePath } from "./EmbedLeafletMap.svelte";
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from "../../utils/imageProxy";
  import AppsRequestComposer from "../apps/AppsRequestComposer.svelte";
  import { text } from "../../i18n/translations";
  import { authStore } from "../../stores/authState";
  import { activeTeamContext } from "../../stores/teamStore";
  import { notificationStore } from "../../stores/notificationStore";
  import {
    APPS_RESULTS_ACTIONS_CONTEXT,
    runAppsWorkspaceRequest,
    type AppsResultsActionsContext,
  } from "../../services/appsWorkspaceRequestService";
  import {
    captureAppsWorkspaceHandoffGuard,
    queueAppsWorkspaceChatHandoff,
    queueAppsWorkspaceWorkflowHandoff,
  } from "../../services/appsWorkspaceChatHandoffService";
  import { setCanonicalFullscreenRoute } from "../../services/embedFullscreenController";
  import {
    EMBED_SOURCE_CHAT_CONTEXT,
    type EmbedSourceChatContext,
  } from "../../types/embedFullscreen";

  type Props = Omit<ComponentProps<typeof UnifiedEmbedFullscreen>, "content" | "fixedBottom" | "floatingBottom"> & {
    /** Visible, safe result metadata only; never encryption keys or transport records. */
    result: Record<string, unknown>;
    summary?: Snippet;
    media?: Snippet;
    detailContent?: Snippet;
    mediaLayout?: "standard" | "immersive";
    mapCenter?: { lat: number; lon: number };
    mapMarkers?: MapMarker[];
    mapZoom?: number;
    mapPath?: MapPathPoint[];
    mapPaths?: MapRoutePath[];
    mapPathColor?: string;
    mapScrollWheelZoom?: boolean;
    onMapReady?: (map: unknown, L: unknown) => void;
    staticMapImageUrl?: string;
  };
  // This Svelte-only adapter forwards the fullscreen API; it is not a custom element.
  // svelte-ignore custom_element_props_identifier
  let {
    result, summary, media, detailContent, mediaLayout = "standard",
    mapCenter, mapMarkers = [], mapZoom = 15, mapPath = [], mapPaths = [],
    mapPathColor, mapScrollWheelZoom = false, onMapReady, staticMapImageUrl,
    ...fullscreen
  }: Props = $props();
  const appId = $derived(fullscreen.appId);
  const currentEmbedId = $derived(fullscreen.currentEmbedId);
  const onClose = $derived(fullscreen.onClose);
  let contentElement = $state<HTMLDivElement>();
  let fullscreenHeight = $state<number>();
  $effect(() => {
    if (mediaLayout !== "immersive" || !contentElement) return;
    const overlay = contentElement.closest<HTMLElement>(".unified-embed-fullscreen-overlay");
    if (!overlay) return;
    // Apps and split panes can be shorter than the viewport. Budget media
    // against the actual shell, independently of its entrance translation.
    const updateHeight = () => { fullscreenHeight = overlay.clientHeight; };
    updateHeight();
    const observer = new ResizeObserver(updateHeight);
    observer.observe(overlay);
    return () => observer.disconnect();
  });
  let failedMapImage = $state<string>();
  const mapImage = $derived(proxyImage(staticMapImageUrl, MAX_WIDTH_HEADER_IMAGE));
  const hasMap = $derived(!!mapCenter || !!mapImage);
  const actions = getContext<AppsResultsActionsContext | undefined>(
    APPS_RESULTS_ACTIONS_CONTEXT,
  );
  const sourceChat = getContext<EmbedSourceChatContext | undefined>(
    EMBED_SOURCE_CHAT_CONTEXT,
  );
  const ownerCurrent = captureAppsWorkspaceHandoffGuard();
  let submitting = $state(false);
  let alive = true;
  let requestController: AbortController | undefined;
  onDestroy(() => { alive = false; requestController?.abort(); });
  $effect(() => {
    // A reused fullscreen must cancel work owned by its previous result.
    void result; void appId; void currentEmbedId;
    return () => { requestController?.abort(); };
  });
  async function submitFollowup(
    value: string,
    attachments: File[],
  ): Promise<boolean> {
    if (!ownerCurrent()) return false;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    const origin = { result, appId, currentEmbedId };
    const isCurrent = () => alive && !controller.signal.aborted && ownerCurrent()
      && origin.result === result && origin.appId === appId && origin.currentEmbedId === currentEmbedId;
    submitting = true;
    try {
      const context = {
        embed_id: currentEmbedId,
        chat_id: sourceChat?.chatId ?? undefined,
        result,
      };
      if (actions) {
        const accepted = await actions.onSubmit(value, attachments, context);
        return isCurrent() && accepted !== false;
      }
      const response = await runAppsWorkspaceRequest({
        appId,
        text: value,
        attachments,
        signal: controller.signal,
        context,
        guest: !get(authStore).isAuthenticated,
        teamId: get(activeTeamContext).teamId ?? undefined,
        onAccepted: ({ embedId }) => {
          if (isCurrent()) setCanonicalFullscreenRoute(embedId);
        },
        onChat: async (request) => { if (isCurrent()) await queueAppsWorkspaceChatHandoff(request); },
        onWorkflow: async (request) => { if (isCurrent()) await queueAppsWorkspaceWorkflowHandoff(request); },
      });
      if (!isCurrent()) return false;
      if (response.action !== "execute") onClose();
      return true;
    } catch {
      if (isCurrent())
        notificationStore.error($text("apps_workspace.request_error"));
      return false;
    } finally {
      if (alive && requestController === controller) submitting = false;
    }
  }
</script>

<UnifiedEmbedFullscreen {...fullscreen} floatingBottom={true}>
  {#snippet content()}
    <div
      bind:this={contentElement}
      style:--result-fullscreen-height={fullscreenHeight ? `${fullscreenHeight}px` : undefined}
      class="result-embed-content"
      class:immersive={mediaLayout === "immersive"}
      data-testid="result-embed-content"
      data-app-id={appId}
    >
      {#if summary}<div class="result-summary" data-testid="result-facts">
        {@render summary()}
      </div>{/if}
      {#if media || hasMap}
        <div
          class="result-media"
          class:split={!!media && hasMap}
          data-testid="result-media"
        >
          {#if media}<div class="result-media-panel">
              {@render media()}
            </div>{/if}
          {#if hasMap}
            <div class="result-map" data-testid="result-map">
              {#if mapImage && failedMapImage !== mapImage}
                <img class="static-map" src={mapImage} alt={$text("apps.maps")} onerror={() => failedMapImage = mapImage} />
              {:else if mapCenter}<EmbedLeafletMap
                center={mapCenter}
                markers={mapMarkers}
                zoom={mapZoom}
                path={mapPath}
                paths={mapPaths}
                pathColor={mapPathColor}
                {onMapReady}
                fitBounds={true}
                scrollWheelZoom={mapScrollWheelZoom}
                zoomControlPosition="topleft"
                controlStyle="compact"
                height="100%"
                minHeight="200px"
              />{:else}<p role="status">{$text("common.detail_load_error", {values: {item: $text("apps.maps")}})}</p>{/if}
            </div>
          {/if}
        </div>
      {/if}
      {#if detailContent}<div class="result-detail-content">{@render detailContent()}</div>{/if}
    </div>
  {/snippet}
  {#snippet fixedBottom()}
    <div class="result-followup">
      <AppsRequestComposer
        presentation="embed"
        {appId}
        {submitting}
        placeholder={$text("apps_workspace.followup_placeholder")}
        onSubmit={submitFollowup}
      />
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .result-embed-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-10);
    width: min(100%, 64rem);
    margin-inline: auto;
    box-sizing: border-box;
    padding: var(--spacing-12) var(--spacing-6) 7rem;
    color: var(--color-font-primary);
  }
  .result-summary {
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: var(--spacing-2);
    background: var(--color-grey-0);
    border-radius: var(--radius-8);
    padding: var(--spacing-2) var(--spacing-4);
    max-width: 100%;
  }
  .result-summary:empty { display: none; }
  .result-media {
    width: 100%;
    min-width: 0;
    display: grid;
    gap: var(--spacing-4);
  }
  .result-media-panel,
  .result-map {
    min-width: 0;
    border-radius: var(--radius-6);
    overflow: hidden;
  }
  .result-map {
    height: clamp(12.5rem, 27vh, 19rem);
    background: var(--color-grey-25);
  }
  .result-detail-content {
    width: min(100%, 34rem);
    display: flex;
    align-items: center;
    flex-direction: column;
    gap: var(--spacing-10);
  }
  .result-detail-content :global(.result-icon-row) {
    display: flex;
    justify-content: center;
    gap: var(--spacing-2);
    flex-wrap: wrap;
  }
  .result-detail-content :global(.result-location) {
    display: flex;
    align-items: center;
    gap: var(--spacing-6);
    width: fit-content;
    max-width: 100%;
    box-sizing: border-box;
    background: var(--color-grey-0);
    border-radius: var(--radius-5);
    padding: var(--spacing-6) var(--spacing-8);
    font-size: 0.875rem;
    line-height: 1.4;
  }
  .result-detail-content :global(.result-description) {
    margin: 0;
    width: 100%;
    font-size: 0.875rem;
    line-height: 1.55;
    white-space: pre-wrap;
  }
  .result-followup {
    width: min(100%, 25rem);
    margin-inline: auto;
  }
  @container fullscreen (min-width: 600px) {
    .result-embed-content {
      padding-inline: var(--spacing-16);
    }
    .result-media.split {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 0;
    }
    .split .result-media-panel {
      border-start-end-radius: 0;
      border-end-end-radius: 0;
    }
    .split .result-map {
      border-start-start-radius: 0;
      border-end-start-radius: 0;
      height: 100%;
      min-height: 15rem;
    }
  }
  .static-map { width: 100%; height: 100%; object-fit: contain; }
  .result-embed-content.immersive { width: 100%; }
  .immersive .result-media-panel { background: transparent; }
  .immersive .result-media-panel :global(.result-primary-media) {
    display: block;
    max-width: 100%;
    max-height: max(12rem, calc(var(--result-fullscreen-height, 100dvh) - 27rem));
    object-fit: contain;
    margin-inline: auto;
  }
</style>
