<!-- Shared result-detail structure; specialized editors retain their own layout. -->
<script lang="ts">
  import { getContext, onDestroy, type Snippet } from "svelte";
  import { get } from "svelte/store";
  import UnifiedEmbedFullscreen from "./UnifiedEmbedFullscreen.svelte";
  import EmbedLeafletMap, { type MapMarker } from "./EmbedLeafletMap.svelte";
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

  interface Props {
    appId: string;
    skillId: string;
    skillIconName: string;
    decorationIconName?: string;
    embedHeaderTitle?: string;
    embedHeaderSubtitle?: string;
    currentEmbedId?: string;
    result: Record<string, unknown>;
    onClose: () => void;
    onCalendar?: () => void;
    showShare?: boolean;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: "previous" | "next";
    showChatButton?: boolean;
    onShowChat?: () => void;
    mapCenter?: { lat: number; lon: number };
    mapMarkers?: MapMarker[];
    mapZoom?: number;
    summary: Snippet;
    media?: Snippet;
    detailContent: Snippet;
    embedHeaderCta?: Snippet;
  }
  let {
    appId,
    skillId,
    skillIconName,
    decorationIconName,
    embedHeaderTitle,
    embedHeaderSubtitle,
    currentEmbedId,
    result,
    onClose,
    onCalendar,
    showShare,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    mapCenter,
    mapMarkers = [],
    mapZoom = 15,
    summary,
    media,
    detailContent,
    embedHeaderCta,
  }: Props = $props();
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

<UnifiedEmbedFullscreen
  {appId}
  {skillId}
  {skillIconName}
  {decorationIconName}
  {embedHeaderTitle}
  {embedHeaderSubtitle}
  {currentEmbedId}
  {onClose}
  {onCalendar}
  {showShare}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  {embedHeaderCta}
  floatingBottom={true}
>
  {#snippet content()}
    <div
      class="result-embed-content"
      data-testid="result-embed-content"
      data-app-id={appId}
    >
      <div class="result-summary" data-testid="result-facts">
        {@render summary()}
      </div>
      {#if media || mapCenter}
        <div
          class="result-media"
          class:split={!!media && !!mapCenter}
          data-testid="result-media"
        >
          {#if media}<div class="result-media-panel">
              {@render media()}
            </div>{/if}
          {#if mapCenter}
            <div class="result-map" data-testid="result-map">
              <EmbedLeafletMap
                center={mapCenter}
                markers={mapMarkers}
                zoom={mapZoom}
                fitBounds={true}
                scrollWheelZoom={false}
                zoomControlPosition="topleft"
                controlStyle="compact"
                height="100%"
                minHeight="200px"
              />
            </div>
          {/if}
        </div>
      {/if}
      <div class="result-detail-content">{@render detailContent()}</div>
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
</style>
