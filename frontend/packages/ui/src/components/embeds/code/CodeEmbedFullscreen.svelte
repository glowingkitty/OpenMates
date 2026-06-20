<!--
  frontend/packages/ui/src/components/embeds/CodeEmbedFullscreen.svelte
  
  Fullscreen view for Code embeds.
  Uses UnifiedEmbedFullscreen as base and provides code-specific content.
  
  Shows:
  - Code filename, language, and line count in header
  - Full syntax-highlighted code (scrollable)
  - Copy button to copy code to clipboard
  - Basic infos bar at the bottom
-->

<script lang="ts">
  import { onMount, tick } from 'svelte';
  // Import highlight.js theme - using github-dark for dark mode compatibility
  import 'highlight.js/styles/github-dark.css';
  // Import shared highlighting utilities (includes all language support + Svelte)
  import { highlightToLines } from './codeHighlighting';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { downloadCodeFile } from '../../../services/zipExportService';
  import { notificationStore } from '../../../stores/notificationStore';
  import { countCodeLines, formatLanguageName, parseCodeEmbedContent } from './codeEmbedContent';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import { includeOriginalPIIInDraftEmbed, loadEmbedPIIMappings } from '../../enter_message/services/codeEmbedService';
  import { piiVisibilityStore } from '../../../stores/piiVisibilityStore';
  import { authStore } from '../../../stores/authStore';
  import { loginInterfaceOpen } from '../../../stores/uiStateStore';
  import type { PIIMapping } from '../../../types/chat';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { codeLineHighlightStore } from '../../../stores/messageHighlightStore';
  import { embedStore } from '../../../services/embedStore';
  import { decodeToonContent, resolveEmbed } from '../../../services/embedResolver';
  import { fetchWithPresignedUrl } from '../../../services/presignedUrlService';
  import { getCodeRunOutputForEmbed } from '../../../services/db/codeRunOutputs';
  import { sendRequestCodeRunOutputImpl, sendUpsertCodeRunOutputImpl } from '../../../services/sendersCodeRunOutputs';
  import { chatDB } from '../../../services/db';
  import { isCodeRunSupported } from './codeRunSupport';
  import CodePreviewPane from './CodePreviewPane.svelte';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import Toggle from '../../Toggle.svelte';
  import { SettingsSectionHeading } from '../../settings/elements';
  import {
    CodeRunStartError,
    cancelCodeRun,
    getCodeRunStatus,
    getCodeRunStreamUrl,
    prepareCodeRun,
    startCodeRun,
    type CodeRunEvent,
    type CodeRunClientAttachment,
    type CodeRunClientFile,
    type CodeRunDependencyInstall,
    type CodeRunDependencySuggestion,
    type CodeRunDependencyVersionOption,
    type CodeRunStatus,
    type CodeRunStreamMessage,
  } from '../../../services/codeRunService';
  import type { CodeRunOutput } from '../../../types/chat';

  /**
   * Props for code embed fullscreen
   */
  interface Props {
    /** Standardized raw embed data (decodedContent, attrs, embedData) */
    data: EmbedFullscreenRawData;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing (from embed:{embed_id} contentRef) */
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
    /** Whether to show the "chat" button to restore chat visibility (ultra-wide forceOverlayMode) */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button to restore chat visibility */
    onShowChat?: () => void;
    /**
     * PII mappings from the parent chat — maps placeholder strings (e.g. "[EMAIL_com]")
     * to original values. When provided and piiRevealed is true, placeholder strings
     * in the code content are replaced with originals for display.
     */
    piiMappings?: PIIMapping[];
    /**
     * Whether PII originals are currently visible.
     * When false (default), placeholder strings like [EMAIL_com] are shown as-is.
     * When true, placeholders are replaced with original values.
     * This is the initial value — the user can toggle locally in fullscreen.
     */
    piiRevealed?: boolean;
    /** Current chat ID — required for piiVisibilityStore.toggle(chatId). See OPE-400. */
    chatId?: string;
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
    piiMappings = [],
    piiRevealed = false,
    chatId
  }: Props = $props();

  // ── Extract fields from data.decodedContent (with attrs fallback) ───────────

  let dc = $derived(data.decodedContent);
  let attrs = $derived(data.attrs);
  let includedOriginalCodeContent = $state<string | null>(null);
  let latestCodeContent = $derived(
      typeof dc.code === 'string' ? dc.code
      : typeof attrs?.code === 'string' ? attrs.code as string
      : ''
    );
  let codeContent = $derived(
      includedOriginalCodeContent !== null ? includedOriginalCodeContent
      : latestCodeContent
    );
  let language = $derived(
      typeof dc.language === 'string' ? dc.language
      : typeof attrs?.language === 'string' ? attrs.language as string
      : ''
    );
  let filename = $derived(
      typeof dc.filename === 'string' ? dc.filename
      : typeof attrs?.filename === 'string' ? attrs.filename as string
      : undefined
    );
  let lineCount = $derived(
      typeof dc.line_count === 'number' ? dc.line_count
      : typeof dc.lineCount === 'number' ? dc.lineCount
      : typeof attrs?.lineCount === 'number' ? attrs.lineCount as number
      : 0
    );
  let versionNumber = $derived(
      typeof dc.version_number === 'number' ? dc.version_number
      : data.embedData?.version_number ?? 1
    );

  // Single source of truth: piiRevealed flows down from piiVisibilityStore via
  // the parent (ActiveChat); togglePII() writes back to the same store so the
  // chat header and embed fullscreen stay in sync. See OPE-400.
  /** Whether there are any PII mappings to apply (controls button visibility) */
  let embedPIIMappings = $state<PIIMapping[]>([]);
  let originalPIIIncluded = $state(false);
  let allPIIMappings = $derived([...piiMappings, ...embedPIIMappings]);
  let hasPII = $derived(allPIIMappings.length > 0);
  let isDraftEmbed = $derived(!data.embedData?.encrypted_content && !data.embedData?.hashed_message_id);
  let canIncludeOriginalPII = $derived(!!embedId && isDraftEmbed && embedPIIMappings.length > 0 && !originalPIIIncluded);

  $effect(() => {
    if (!embedId) return;
    let cancelled = false;
    loadEmbedPIIMappings(embedId).then((mappings) => {
      if (!cancelled) embedPIIMappings = mappings;
    });
    return () => { cancelled = true; };
  });

  function togglePII() {
    if (!chatId) return;
    piiVisibilityStore.toggle(chatId);
  }

  async function includeOriginalPII() {
    if (!embedId) return;
    try {
      const count = await includeOriginalPIIInDraftEmbed(embedId);
      includedOriginalCodeContent = restorePIIInText(codeContent, embedPIIMappings);
      embedPIIMappings = [];
      originalPIIIncluded = true;
      notificationStore.success($text('embeds.pii_include_original_success', { values: { count: String(count) } }));
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to include original PII:', error);
      notificationStore.error($text('embeds.pii_include_original_failed'));
    }
  }

  /**
   * Apply PII masking to the raw code string before parsing/displaying.
   * When piiRevealed is true, restore originals; otherwise keep placeholders.
   */
  let piiProcessedCodeContent = $derived.by(() => {
    if (!hasPII || !codeContent) return codeContent;
    if (piiRevealed) {
      return restorePIIInText(codeContent, allPIIMappings);
    } else {
      return replacePIIOriginalsWithPlaceholders(codeContent, allPIIMappings);
    }
  });

  // Parse code content to extract language, filename, and actual code
  let parsedContent = $derived.by(() => parseCodeEmbedContent(piiProcessedCodeContent, { language, filename }));
  let renderCodeContent = $derived(parsedContent.code);
  let renderLanguage = $derived(parsedContent.language || '');
  let renderFilename = $derived(parsedContent.filename);
  let displayLanguage = $derived.by(() => formatLanguageName(renderLanguage));
  
  // Calculate actual line count from content if not provided
  let actualLineCount = $derived.by(() => {
    if (lineCount > 0) return lineCount;
    return countCodeLines(renderCodeContent);
  });

  /**
   * Per-line highlighted HTML fragments.
   * Re-computed whenever the code content or language changes.
   * Each element is a sanitized HTML string for one source line.
   */
  let highlightedLines = $derived(highlightToLines(renderCodeContent, renderLanguage));

  /**
   * The line range to highlight, sourced from the global codeLineHighlightStore.
   * Set when the user clicks an embed: link with a #L42 / #L10-L20 suffix.
   * Null when no line highlighting is requested.
   * $codeLineHighlightStore uses Svelte's auto-subscribe rune syntax — it
   * reactively re-evaluates anywhere it is referenced in this component.
   */
  let focusLineRange = $derived(data.focusLineRange ?? null);
  let highlightRange = $derived($codeLineHighlightStore ?? focusLineRange);

  /**
   * Reference to the code lines container — used to query-select the first
   * highlighted line element for auto-scrolling.
   */
  let codeLinesContainer: HTMLElement | null = $state(null);

  /**
   * Scroll the first highlighted line into view (centered).
   * Safe to call before the DOM is rendered — does nothing if container is null.
   */
  async function scrollToHighlightedLine() {
    if (!codeLinesContainer || !highlightRange) return;
    await tick();
    const startLine = codeLinesContainer.querySelector(
      `.code-line[data-line="${highlightRange.start}"]`
    ) as HTMLElement | null;
    if (startLine) {
      requestAnimationFrame(() => {
        startLine.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
      });
    }
  }

  // Auto-scroll to the first highlighted line after mount.
  onMount(() => {
    scrollToHighlightedLine();
  });

  // Also scroll whenever the highlight range changes while the fullscreen is open.
  $effect(() => {
    // Reactive dependency on highlightRange — re-runs when the store value changes.
    void highlightRange;
    scrollToHighlightedLine();
  });
  
  // Build skill name for BasicInfosBar: filename (or "Code snippet")
  let skillName = $derived.by(() => {
    // If filename is provided, extract just the filename from path if needed
    const effectiveFilename = renderFilename;
    if (effectiveFilename) {
      // Extract filename from filepath (handle both forward and backslash paths)
      const pathParts = effectiveFilename.split(/[/\\]/);
      return pathParts[pathParts.length - 1];
    }
    // If no filename provided, use translation for "Code snippet"
    return $text('embeds.code_snippet');
  });
  
  // Build status text: line count + language (always use code_info.text format)
  let statusText = $derived.by(() => {
    const lineCount = actualLineCount;
    if (lineCount === 0) return '';
    
    // Build line count text with proper singular/plural handling
    const lineCountText = lineCount === 1 
      ? $text('embeds.code_line_singular')
      : $text('embeds.code_line_plural');
    
    const languageToShow = displayLanguage;
    return languageToShow ? `${lineCount} ${lineCountText}, ${languageToShow}` : `${lineCount} ${lineCountText}`;
  });
  
  // Map skillId to icon name
  const skillIconName = 'coding';
  
  // Handle copy code to clipboard.
  // Copies the PII-processed content (original values if revealed, placeholders if hidden).
  async function handleCopy() {
    try {
      const result = await copyToClipboard(renderCodeContent);
      if (!result.success) throw new Error(result.error || 'Copy failed');
      console.debug('[CodeEmbedFullscreen] Copied code to clipboard');
      notificationStore.success($text('embeds.copied_to_clipboard'));
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to copy code:', error);
      notificationStore.error($text('embeds.copy_failed'));
    }
  }

  // Handle download code file
  async function handleDownload() {
    try {
      console.debug('[CodeEmbedFullscreen] Starting code file download');
      await downloadCodeFile(renderCodeContent, renderLanguage, renderFilename);
      notificationStore.success($text('embeds.code_file_downloaded'));
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to download code file:', error);
      notificationStore.error($text('embeds.code_file_download_failed'));
    }
  }

  // ── Preview/Render mode ─────────────────────────────────────────────

  /** Languages that support preview rendering. */
  const PREVIEWABLE_LANGUAGES = new Set(['markdown', 'md', 'html', 'htm', 'xml']);

  /** File extensions that support preview rendering. */
  const PREVIEWABLE_EXTENSIONS = new Set(['.md', '.markdown', '.html', '.htm']);

  /**
   * Whether this code embed supports preview rendering.
   * True for markdown/HTML content (detected by language or filename extension).
   */
  let isPreviewable = $derived.by(() => {
    if (PREVIEWABLE_LANGUAGES.has(renderLanguage.toLowerCase())) return true;
    if (renderFilename) {
      const ext = renderFilename.slice(renderFilename.lastIndexOf('.')).toLowerCase();
      if (PREVIEWABLE_EXTENSIONS.has(ext)) return true;
    }
    return false;
  });

  /**
   * Determine the preview type based on language/filename.
   * Returns 'markdown' or 'html'.
   */
  let previewType = $derived.by(() => {
    const lang = renderLanguage.toLowerCase();
    if (lang === 'markdown' || lang === 'md') return 'markdown' as const;
    if (renderFilename) {
      const ext = renderFilename.slice(renderFilename.lastIndexOf('.')).toLowerCase();
      if (ext === '.md' || ext === '.markdown') return 'markdown' as const;
    }
    return 'html' as const;
  });

  /** Whether preview mode is currently active (toggled by the preview button). */
  let previewActive = $state(false);

  const INSTALL_SNIPPET_LANGUAGES = new Set(['bash', 'sh', 'shell', 'terminal', 'console']);
  const PYTHON_PACKAGE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:(?:==|~=|!=|<=|>=|<|>)[A-Za-z0-9.*+!_-]+)?$/;
  const NPM_PACKAGE_PATTERN = /^(?:@[a-z0-9][a-z0-9._-]*\/[a-z0-9][a-z0-9._-]*|[a-z0-9][a-z0-9._-]*)(?:@[A-Za-z0-9._~^*-]+)?$/;

  let runPanelOpen = $state(false);
  let runStatus = $state<CodeRunStatus['status'] | 'idle'>('idle');
  let runExecutionId = $state<string | null>(null);
  let runEvents = $state<CodeRunEvent[]>([]);
  let runFiles = $state<string[]>([]);
  let runError = $state<string | null>(null);
  let runCancelRequested = $state(false);
  let runPollTimer: ReturnType<typeof setTimeout> | null = null;
  let runSocket: WebSocket | null = null;
  let persistedRunExecutionId = $state<string | null>(null);

  interface SavedCodeRunOutput {
    id?: string;
    text: string;
    status?: CodeRunStatus['status'];
    files?: string[];
    savedAt?: number;
    events?: CodeRunEvent[];
  }

  let isRunnable = $derived.by(() => isCodeRunSupported(renderLanguage, renderFilename));

  const TERMINAL_RUN_STATUSES = new Set(['finished', 'failed', 'timeout', 'cancelled']);
  const CLIENT_CONTENT_REQUIRED_CODE = 'client_content_required';

  interface CodeRunAttachmentSource {
    s3Key: string;
    path: string;
    aesKey: string;
    aesNonce: string;
    mimeType: string;
  }

  interface CodeRunFileCandidate {
    id: string;
    embedId: string;
    kind: 'code' | 'attachment' | 'dependency';
    title: string;
    subtitle: string;
    selected: boolean;
    required: boolean;
    clientFile?: CodeRunClientFile;
    attachmentSources?: CodeRunAttachmentSource[];
    dependencyInstall?: CodeRunDependencyInstall;
    dependencyPackage?: string;
    dependencyImportName?: string;
    dependencyVersionOptions?: CodeRunDependencyVersionOption[];
    selectedVersion?: string;
  }

  let runActive = $derived(runStatus !== 'idle' && !TERMINAL_RUN_STATUSES.has(runStatus));
  let runSelectionOpen = $state(false);
  let runSelectionLoading = $state(false);
  let runSelectionError = $state<string | null>(null);
  let runCandidates = $state<CodeRunFileCandidate[]>([]);
  let requestedRunOutputKey = $state<string | null>(null);
  let codeRunOverlayActive = $derived(runPanelOpen || runSelectionOpen);
  let outputPaneActive = $derived(previewActive);
  let splitPaneActive = $derived(outputPaneActive || codeRunOverlayActive);
  let hasCodeHeaderCta = $derived(((isRunnable && !!embedId && !codeRunOverlayActive) || isPreviewable));
  let savedRunOutput = $state<SavedCodeRunOutput | null>(null);
  let runDisplayEvents = $derived(buildCompactRunEvents(runEvents));
  let selectableRunCandidates = $derived(runCandidates.filter((candidate) => !candidate.required));
  let allOptionalCandidatesSelected = $derived(selectableRunCandidates.length > 0 && selectableRunCandidates.every((candidate) => candidate.selected));
  let selectedRunCandidates = $derived(runCandidates.filter((candidate) => candidate.selected || candidate.required));
  let runCtaLabel = $derived.by(() => {
    if (runActive || runEvents.length > 0) return $text('app_skills.code.run.show_output');
    if (savedRunOutput) return $text('app_skills.code.run.show_output');
    return $text('app_skills.code.run_code');
  });

  function readSavedRunOutput(content: Record<string, unknown>): SavedCodeRunOutput | null {
    const text = content.code_run_output;
    if (typeof text !== 'string' || !text.trim()) return null;
    const status = typeof content.code_run_status === 'string'
      ? content.code_run_status as CodeRunStatus['status']
      : undefined;
    const files = Array.isArray(content.code_run_files)
      ? content.code_run_files.filter((file): file is string => typeof file === 'string')
      : undefined;
    const events = Array.isArray(content.code_run_events)
      ? content.code_run_events.filter((event): event is CodeRunEvent => {
        if (!event || typeof event !== 'object') return false;
        const candidate = event as Record<string, unknown>;
        return (
          (candidate.kind === 'status' || candidate.kind === 'stdout' || candidate.kind === 'stderr')
          && typeof candidate.text === 'string'
          && typeof candidate.timestamp === 'number'
        );
      })
      : undefined;
    const savedAt = typeof content.code_run_saved_at === 'number' ? content.code_run_saved_at : undefined;
    return { text, status, files, savedAt, events };
  }

  function savedRunOutputFromRow(row: CodeRunOutput): SavedCodeRunOutput {
    return {
      id: row.id,
      text: row.output,
      status: row.status as CodeRunStatus['status'] | undefined,
      files: row.files,
      savedAt: row.saved_at,
      events: row.events as CodeRunEvent[] | undefined,
    };
  }

  function codeRunOutputRef(embedIdValue: string): string {
    return `code-run-output:${embedIdValue}`;
  }

  async function loadSavedRunOutput() {
    if (!embedId) return;
    try {
      const syncedOutput = await getCodeRunOutputForEmbed(chatDB, embedId);
      if (syncedOutput) {
        const output = savedRunOutputFromRow(syncedOutput);
        if (savedRunOutput?.text !== output.text || savedRunOutput?.id !== output.id) {
          savedRunOutput = output;
        }
      }

      const sidecar = syncedOutput ? null : await embedStore.get(codeRunOutputRef(embedId));
      if (!sidecar || typeof sidecar !== 'object') return;
      const output = readSavedRunOutput(sidecar as Record<string, unknown>);
      if (output && savedRunOutput?.text !== output.text) {
        savedRunOutput = output;
        if (chatId) {
          const now = Math.floor(Date.now() / 1000);
          await sendUpsertCodeRunOutputImpl({
            id: crypto.randomUUID(),
            chat_id: chatId,
            embed_id: embedId,
            output: output.text,
            status: output.status,
            files: output.files,
            events: output.events,
            saved_at: output.savedAt ?? Date.now(),
            created_at: now,
            updated_at: now,
          });
        }
      }
    } catch (error) {
      console.warn('[CodeEmbedFullscreen] Failed to load saved code run output:', error);
    }
  }

  $effect(() => {
    void embedId;
    void loadSavedRunOutput();
    const requestKey = chatId && embedId ? `${chatId}:${embedId}` : null;
    if (chatId && embedId && requestedRunOutputKey !== requestKey) {
      requestedRunOutputKey = requestKey;
      void sendRequestCodeRunOutputImpl(chatId, embedId);
    }
  });

  onMount(() => {
    const handleSyncedOutput = (event: Event) => {
      const output = (event as CustomEvent<CodeRunOutput>).detail;
      if (!embedId || output.embed_id !== embedId) return;
      savedRunOutput = savedRunOutputFromRow(output);
      if (!runActive && !runPanelOpen) {
        runEvents = savedOutputToEvents(savedRunOutput);
        runStatus = savedRunOutput.status ?? 'finished';
        runFiles = savedRunOutput.files ?? [];
      }
    };
    window.addEventListener('codeRunOutputSynced', handleSyncedOutput);
    return () => window.removeEventListener('codeRunOutputSynced', handleSyncedOutput);
  });

  function savedOutputToEvents(output: SavedCodeRunOutput): CodeRunEvent[] {
    if (output.events?.length) return output.events;
    const lines = output.text.endsWith('\n') ? output.text : `${output.text}\n`;
    return lines.split(/(?<=\n)/).filter(Boolean).map((line) => ({
      kind: 'status',
      text: line,
      timestamp: output.savedAt ? output.savedAt / 1000 : Date.now() / 1000,
    }));
  }

  function cloneRunEvents(events: CodeRunEvent[]): CodeRunEvent[] {
    return events.map(({ kind, text, timestamp }) => ({ kind, text, timestamp }));
  }

  function isDependencyInstallEvent(event: CodeRunEvent): boolean {
    const text = event.text.trimStart();
    return (
      event.kind === 'status' && text.startsWith('Installing selected ')
      || text.startsWith('Collecting ')
      || text.startsWith('Obtaining dependency information for ')
      || text.startsWith('Downloading ')
      || text.startsWith('Installing collected packages:')
      || text.startsWith('Successfully installed ')
      || text.startsWith('Requirement already satisfied:')
    );
  }

  function hasFailedFinalStatus(events: CodeRunEvent[]): boolean {
    return events.some((event) => {
      const text = event.text.trimStart();
      return event.kind === 'status' && (text.startsWith('Exited ') && !text.includes('code 0'));
    });
  }

  function hasSuccessfulFinalStatus(events: CodeRunEvent[]): boolean {
    return events.some((event) => {
      const text = event.text.trimStart();
      return event.kind === 'status' && text.startsWith('Exited ') && text.includes('code 0');
    });
  }

  function omitSuccessfulDependencyInstallEvents(events: CodeRunEvent[]): CodeRunEvent[] {
    const filtered: CodeRunEvent[] = [];
    let inInstallBlock = false;
    for (const event of events) {
      const text = event.text.trimStart();
      if (event.kind === 'status' && text.startsWith('Installing selected ')) {
        inInstallBlock = true;
        continue;
      }
      if (inInstallBlock && event.kind === 'status' && text.startsWith('Running ')) {
        inInstallBlock = false;
        filtered.push(event);
        continue;
      }
      if (inInstallBlock && isDependencyInstallEvent(event)) continue;
      if (!inInstallBlock) filtered.push(event);
    }
    return filtered;
  }

  function buildCompactRunEvents(events: CodeRunEvent[]): CodeRunEvent[] {
    const compactEvents = events.filter((event) => !event.text.startsWith('Queued code run for'));
    if (!hasSuccessfulFinalStatus(compactEvents) || hasFailedFinalStatus(compactEvents)) return compactEvents;
    return omitSuccessfulDependencyInstallEvents(compactEvents);
  }

  function compactRunOutputText(): string {
    return runDisplayEvents.map((event) => event.text).join('').trimEnd();
  }

  function programRunOutputText(): string {
    return runDisplayEvents
      .filter((event) => event.kind === 'stdout' || event.kind === 'stderr')
      .map((event) => event.text)
      .join('')
      .trimEnd();
  }

  let hasProgramRunOutput = $derived(Boolean(programRunOutputText()));

  async function handleCopyRunOutput() {
    try {
      const output = programRunOutputText();
      if (!output) return;
      const result = await copyToClipboard(output);
      if (!result.success) throw new Error(result.error || 'Copy failed');
      notificationStore.success($text('app_skills.code.run.output_copied'));
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to copy code run output:', error);
      notificationStore.error($text('app_skills.code.run.output_copy_failed'));
    }
  }

  async function handleAskRunOutputFollowup() {
    try {
      const output = programRunOutputText();
      if (!output) return;
      const result = await copyToClipboard(output);
      if (!result.success) throw new Error(result.error || 'Copy failed');
      window.dispatchEvent(new CustomEvent('codeRunOutputFollowup', { detail: { output } }));
      onShowChat?.();
      onClose();
      notificationStore.success($text('app_skills.code.run.followup_inserted'));
    } catch (error) {
      console.error('[CodeEmbedFullscreen] Failed to prepare code run output follow-up:', error);
      notificationStore.error($text('app_skills.code.run.followup_failed'));
    }
  }

  function compactRunOutputHasFinalLine(): boolean {
    return runDisplayEvents.some((event) => event.kind === 'status' && (event.text.startsWith('Exited ') || event.text.startsWith('Cancelled ')));
  }

  async function persistRunOutput() {
    if (!embedId || !runExecutionId || persistedRunExecutionId === runExecutionId) return;
    if (!chatId) {
      console.warn('[CodeEmbedFullscreen] Cannot sync Code Run output without chatId');
      return;
    }
    const outputText = compactRunOutputText();
    if (!outputText || !compactRunOutputHasFinalLine()) return;

    persistedRunExecutionId = runExecutionId;
    const savedAt = Date.now();
    const now = Math.floor(savedAt / 1000);
    const outputId = savedRunOutput?.id ?? crypto.randomUUID();
    const plainFiles = runFiles.filter((file) => typeof file === 'string');
    const plainEvents = cloneRunEvents(runDisplayEvents);
    try {
      await sendUpsertCodeRunOutputImpl({
        id: outputId,
        chat_id: chatId,
        embed_id: embedId,
        output: outputText,
        status: runStatus as CodeRunStatus['status'],
        files: plainFiles,
        events: plainEvents,
        saved_at: savedAt,
        created_at: now,
        updated_at: now,
      });
      savedRunOutput = {
        id: outputId,
        text: outputText,
        status: runStatus as CodeRunStatus['status'],
        files: plainFiles,
        savedAt,
        events: plainEvents,
      };
    } catch (error) {
      console.warn('[CodeEmbedFullscreen] Failed to persist code run output:', error);
      persistedRunExecutionId = null;
    }
  }

  function togglePreview() {
    previewActive = !previewActive;
  }

  function toggleRunOutput() {
    if (codeRunOverlayActive) return;
    if (runExecutionId || runEvents.length > 0) {
      previewActive = false;
      runSelectionOpen = false;
      runPanelOpen = true;
      return;
    }
    if (savedRunOutput) {
      previewActive = false;
      runPanelOpen = true;
      runStatus = savedRunOutput.status || 'finished';
      runFiles = savedRunOutput.files || [];
      runEvents = savedOutputToEvents(savedRunOutput);
      runError = null;
      return;
    }
    if (!$authStore.isAuthenticated) {
      loginInterfaceOpen.set(true);
      return;
    }
    openRunSelectionOrRun();
  }

  function closeCodeRunOverlay() {
    runSelectionOpen = false;
    runPanelOpen = false;
  }

  function normalizeEmbedType(value: unknown): string {
    return typeof value === 'string' ? value.toLowerCase() : '';
  }

  function pickFileVariant(files: unknown): Record<string, unknown> | null {
    if (!files || typeof files !== 'object') return null;
    const record = files as Record<string, unknown>;
    for (const name of ['original', 'full', 'audio', 'source', 'preview']) {
      const variant = record[name];
      if (variant && typeof variant === 'object' && typeof (variant as Record<string, unknown>).s3_key === 'string') {
        return variant as Record<string, unknown>;
      }
    }
    for (const variant of Object.values(record)) {
      if (variant && typeof variant === 'object' && typeof (variant as Record<string, unknown>).s3_key === 'string') {
        return variant as Record<string, unknown>;
      }
    }
    return null;
  }

  function fileExtension(decoded: Record<string, unknown>, variant: Record<string, unknown>): string {
    const format = variant.format;
    if (typeof format === 'string' && format) return `.${format.replace(/^\./, '').toLowerCase()}`;
    const mimeType = decoded.content_type || decoded.mime_type;
    if (typeof mimeType === 'string' && mimeType.includes('/')) return `.${mimeType.split('/').pop()?.toLowerCase() || 'bin'}`;
    return '.bin';
  }

  function attachmentTitle(decoded: Record<string, unknown>, embedIdValue: string, variant: Record<string, unknown>): string {
    const title = decoded.filename || decoded.original_filename;
    if (typeof title === 'string' && title.trim()) return title;
    return `attachment-${embedIdValue.slice(0, 8)}${fileExtension(decoded, variant)}`;
  }

  function attachmentMimeType(decoded: Record<string, unknown>): string {
    const mimeType = decoded.content_type || decoded.mime_type;
    return typeof mimeType === 'string' && mimeType ? mimeType : 'application/octet-stream';
  }

  function safeInstallPackagesFromLine(line: string): CodeRunDependencyInstall | null {
    if (/[;&|<>`$\\]/.test(line)) return null;
    const trimmed = line.trim();
    const pythonMatch = trimmed.match(/^(?:pip3?\s+install|python3?\s+-m\s+pip\s+install)\s+(.+)$/);
    const npmMatch = trimmed.match(/^npm\s+(?:install|i)\s+(.+)$/);
    const ecosystem = pythonMatch ? 'python' : npmMatch ? 'npm' : null;
    const rawPackages = pythonMatch?.[1] ?? npmMatch?.[1] ?? '';
    if (!ecosystem || !rawPackages.trim()) return null;

    const packages = rawPackages.split(/\s+/).filter(Boolean);
    if (packages.length === 0 || packages.some((pkg) => pkg.startsWith('-'))) return null;
    const pattern = ecosystem === 'python' ? PYTHON_PACKAGE_PATTERN : NPM_PACKAGE_PATTERN;
    if (!packages.every((pkg) => pattern.test(pkg))) return null;
    return { ecosystem, packages };
  }

  function detectInstallSnippets(code: string, language: string): CodeRunDependencyInstall[] {
    const normalizedLanguage = language.toLowerCase();
    if (normalizedLanguage && !INSTALL_SNIPPET_LANGUAGES.has(normalizedLanguage)) return [];
    const installs = new Map<string, Set<string>>();
    let sawInstall = false;

    for (const rawLine of code.split('\n')) {
      const line = rawLine.trim();
      if (!line || line.startsWith('#')) continue;
      const install = safeInstallPackagesFromLine(line);
      if (!install) return [];
      sawInstall = true;
      const packages = installs.get(install.ecosystem) ?? new Set<string>();
      for (const pkg of install.packages) packages.add(pkg);
      installs.set(install.ecosystem, packages);
    }

    if (!sawInstall) return [];
    return Array.from(installs.entries()).map(([ecosystem, packages]) => ({
      ecosystem: ecosystem as CodeRunDependencyInstall['ecosystem'],
      packages: Array.from(packages),
    }));
  }

  function dependencyCandidate(embedIdValue: string, install: CodeRunDependencyInstall): CodeRunFileCandidate {
    const packageList = install.packages.join(', ');
    return {
      id: `dependency:${install.ecosystem}:${embedIdValue}:${install.packages.join('|')}`,
      embedId: embedIdValue,
      kind: 'dependency',
      title: packageList,
      subtitle: $text('app_skills.code.run.detected_install_command'),
      selected: true,
      required: false,
      dependencyInstall: install,
    };
  }

  function dependencyPackageSpec(ecosystem: CodeRunDependencyInstall['ecosystem'], packageName: string, version: string): string {
    return ecosystem === 'python' ? `${packageName}==${version}` : `${packageName}@${version}`;
  }

  function formatDependencyReleaseDate(value?: string | null): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function dependencySuggestionCandidate(suggestion: CodeRunDependencySuggestion): CodeRunFileCandidate {
    const version = suggestion.latest_version;
    const packageSpec = dependencyPackageSpec(suggestion.ecosystem, suggestion.package, version);
    const released = formatDependencyReleaseDate(suggestion.latest_released_at);
    return {
      id: `dependency:${suggestion.ecosystem}:${suggestion.package}`,
      embedId: `dependency:${suggestion.package}`,
      kind: 'dependency',
      title: suggestion.package,
      subtitle: released
        ? $text('app_skills.code.run.detected_import_latest_release', { values: { importName: suggestion.import_name, version, releaseDate: released } })
        : $text('app_skills.code.run.detected_import_latest', { values: { importName: suggestion.import_name, version } }),
      selected: true,
      required: false,
      dependencyPackage: suggestion.package,
      dependencyImportName: suggestion.import_name,
      dependencyVersionOptions: suggestion.versions,
      selectedVersion: version,
      dependencyInstall: {
        ecosystem: suggestion.ecosystem,
        packages: [packageSpec],
      },
    };
  }

  function updateDependencyVersion(candidateId: string, version: string) {
    runCandidates = runCandidates.map((candidate) => {
      if (candidate.id !== candidateId || !candidate.dependencyInstall || !candidate.dependencyPackage) return candidate;
      return {
        ...candidate,
        selectedVersion: version,
        dependencyInstall: {
          ecosystem: candidate.dependencyInstall.ecosystem,
          packages: [dependencyPackageSpec(candidate.dependencyInstall.ecosystem, candidate.dependencyPackage, version)],
        },
      };
    });
  }

  function arrayBufferToBase64(buffer: ArrayBuffer): string {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  }

  function base64ToArrayBuffer(base64: string): ArrayBuffer {
    const normalized = base64.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(normalized);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }

  async function decryptAttachmentSource(source: CodeRunAttachmentSource): Promise<CodeRunClientAttachment> {
    const encryptedData = await fetchWithPresignedUrl(source.s3Key);
    const nonceBytes = source.aesNonce === '' ? encryptedData.slice(0, 12) : base64ToArrayBuffer(source.aesNonce);
    const ciphertext = source.aesNonce === '' ? encryptedData.slice(12) : encryptedData;
    const cryptoKey = await crypto.subtle.importKey('raw', base64ToArrayBuffer(source.aesKey), { name: 'AES-GCM' }, false, ['decrypt']);
    const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonceBytes }, cryptoKey, ciphertext);
    return {
      embed_id: '',
      path: source.path,
      content_base64: arrayBufferToBase64(decrypted),
      mime_type: source.mimeType,
    };
  }

  async function buildRunCandidates(): Promise<CodeRunFileCandidate[]> {
    const ids = Array.from(new Set([embedId, ...(data.chatEmbedIds || [])].filter((id): id is string => typeof id === 'string' && !!id)));
    const candidates: CodeRunFileCandidate[] = [{
      id: embedId || '',
      embedId: embedId || '',
      kind: 'code',
      title: renderFilename || $text('embeds.code_snippet'),
      subtitle: $text('app_skills.code.run.required_file'),
      selected: true,
      required: true,
      clientFile: {
        embed_id: embedId || '',
        code: renderCodeContent,
        language: renderLanguage,
        ...(renderFilename ? { filename: renderFilename } : {}),
        is_target: true,
      },
    }];

    for (const id of ids) {
      if (!id || id === embedId) continue;
      const resolved = await resolveEmbed(id);
      const decoded = resolved?.content ? await decodeToonContent(resolved.content) : null;
      if (!decoded) continue;
      const type = normalizeEmbedType(decoded.type || resolved?.type);
      if (type === 'code' || type === 'code-code') {
        const parsed = parseCodeEmbedContent(String(decoded.code || decoded.content || ''), {
          language: typeof decoded.language === 'string' ? decoded.language : '',
          filename: typeof decoded.filename === 'string' ? decoded.filename : undefined,
        });
        if (!parsed.code) continue;
        const dependencyInstalls = detectInstallSnippets(parsed.code, parsed.language || '');
        if (dependencyInstalls.length > 0) {
          candidates.push(...dependencyInstalls.map((install) => dependencyCandidate(id, install)));
          continue;
        }
        candidates.push({
          id,
          embedId: id,
          kind: 'code',
          title: parsed.filename || $text('embeds.code_snippet'),
          subtitle: parsed.language || 'code',
          selected: true,
          required: false,
          clientFile: {
            embed_id: id,
            code: parsed.code,
            language: parsed.language || '',
            ...(parsed.filename ? { filename: parsed.filename } : {}),
          },
        });
        continue;
      }

      const variant = pickFileVariant(decoded.files || decoded.s3_files);
      const aesKey = typeof decoded.aes_key === 'string' ? decoded.aes_key : undefined;
      const aesNonce = typeof decoded.aes_nonce === 'string' ? decoded.aes_nonce : undefined;
      if (!variant || typeof variant.s3_key !== 'string') continue;
      const title = attachmentTitle(decoded, id, variant);
      candidates.push({
        id,
        embedId: id,
        kind: 'attachment',
        title,
        subtitle: attachmentMimeType(decoded),
        selected: true,
        required: false,
        attachmentSources: aesKey && aesNonce !== undefined ? [{
          s3Key: variant.s3_key,
          path: title,
          aesKey,
          aesNonce,
          mimeType: attachmentMimeType(decoded),
        }] : [],
      });
    }

    const codeClientFiles = candidates
      .filter((candidate): candidate is CodeRunFileCandidate & { clientFile: CodeRunClientFile } => candidate.kind === 'code' && !!candidate.clientFile)
      .map((candidate) => candidate.clientFile);
    const hasExplicitDependencyCandidates = candidates.some((candidate) => candidate.kind === 'dependency');
    if (chatId && embedId && codeClientFiles.length > 0 && !hasExplicitDependencyCandidates) {
      try {
        const prepared = await prepareCodeRun(chatId, embedId, codeClientFiles, codeClientFiles.map((file) => file.embed_id));
        const existingDependencyKeys = new Set(
          candidates
            .filter((candidate) => candidate.kind === 'dependency' && candidate.dependencyInstall)
            .flatMap((candidate) => candidate.dependencyInstall?.packages || [])
            .map((packageSpec) => packageSpec.toLowerCase())
        );
        for (const suggestion of prepared.dependency_suggestions) {
          if (!existingDependencyKeys.has(suggestion.package.toLowerCase())) {
            candidates.push(dependencySuggestionCandidate(suggestion));
          }
        }
      } catch (error) {
        console.warn('[CodeEmbedFullscreen] Failed to prepare dependency suggestions:', error);
      }
    }

    return candidates;
  }

  async function openRunSelectionOrRun() {
    if (!chatId || !embedId || runActive) return;
    runSelectionLoading = true;
    runSelectionError = null;
    try {
      const candidates = await buildRunCandidates();
      runCandidates = candidates;
      if (candidates.length <= 1) {
        await handleRun(candidates);
        return;
      }
      previewActive = false;
      runPanelOpen = false;
      runSelectionOpen = true;
    } catch (error) {
      runSelectionError = error instanceof Error ? error.message : 'Could not load chat files';
      runSelectionOpen = true;
    } finally {
      runSelectionLoading = false;
    }
  }

  function toggleRunCandidate(candidateId: string) {
    runCandidates = runCandidates.map((candidate) => (
      candidate.id === candidateId && !candidate.required
        ? { ...candidate, selected: !candidate.selected }
        : candidate
    ));
  }

  function toggleAllOptionalCandidates() {
    const nextSelected = !allOptionalCandidatesSelected;
    runCandidates = runCandidates.map((candidate) => candidate.required ? candidate : { ...candidate, selected: nextSelected });
  }

  async function selectedClientAttachments(candidates: CodeRunFileCandidate[]): Promise<CodeRunClientAttachment[]> {
    const attachments: CodeRunClientAttachment[] = [];
    for (const candidate of candidates) {
      if (candidate.kind !== 'attachment' || !candidate.attachmentSources?.length) continue;
      for (const source of candidate.attachmentSources) {
        const attachment = await decryptAttachmentSource(source);
        attachments.push({ ...attachment, embed_id: candidate.embedId });
      }
    }
    return attachments;
  }

  function clearRunPollTimer() {
    if (runPollTimer) {
      clearTimeout(runPollTimer);
      runPollTimer = null;
    }
  }

  function closeRunSocket() {
    if (runSocket) {
      runSocket.onclose = null;
      runSocket.onerror = null;
      runSocket.onmessage = null;
      runSocket.close();
      runSocket = null;
    }
  }

  function syncRunStatus(status: CodeRunStatus) {
    runStatus = status.status;
    runCancelRequested = status.status === 'cancelling';
    runEvents = status.events || [];
    runFiles = status.files || runFiles;
    runError = status.error || null;
  }

  function applyRunUpdate(update: Partial<CodeRunStatus>) {
    if (update.status) runStatus = update.status;
    if (update.status === 'cancelling') runCancelRequested = true;
    if (update.status && TERMINAL_RUN_STATUSES.has(update.status)) runCancelRequested = false;
    if (update.files) runFiles = update.files;
    if (update.error !== undefined) runError = update.error || null;
  }

  function appendRunEvent(event: CodeRunEvent) {
    runEvents = [...runEvents, event];
  }

  function openRunStream(executionId: string) {
    closeRunSocket();

    const socket = new WebSocket(getCodeRunStreamUrl(executionId));
    runSocket = socket;

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as CodeRunStreamMessage;
      if (message.type === 'code_run_snapshot') {
        syncRunStatus(message.payload);
        return;
      }
      if (message.type === 'code_run_update') {
        applyRunUpdate(message.payload);
        return;
      }
      if (message.type === 'code_run_event') {
        appendRunEvent(message.payload);
      }
    };

    socket.onerror = () => {
      socket.close();
    };

    socket.onclose = () => {
      if (runSocket === socket) {
        runSocket = null;
      }
      if (runExecutionId === executionId && !TERMINAL_RUN_STATUSES.has(runStatus)) {
        pollRunStatus(executionId);
      }
    };
  }

  async function pollRunStatus(executionId: string) {
    try {
      const status = await getCodeRunStatus(executionId);
      syncRunStatus(status);
      if (!TERMINAL_RUN_STATUSES.has(status.status)) {
        runPollTimer = setTimeout(() => pollRunStatus(executionId), 1000);
      }
    } catch (error) {
      runStatus = 'failed';
      runError = error instanceof Error ? error.message : 'Code run status unavailable';
      runEvents = [...runEvents, { kind: 'stderr', text: `${runError}\n`, timestamp: Date.now() / 1000 }];
    }
  }

  async function handleRun(candidatesOverride?: CodeRunFileCandidate[]) {
    if (!$authStore.isAuthenticated) {
      loginInterfaceOpen.set(true);
      return;
    }
    if (!chatId || !embedId || runActive) return;
    const candidates = candidatesOverride || selectedRunCandidates;
    const selectedEmbedIds = candidates
      .filter((candidate) => candidate.kind !== 'dependency')
      .map((candidate) => candidate.embedId);
    const selectedCodeFiles = candidates
      .filter((candidate): candidate is CodeRunFileCandidate & { clientFile: CodeRunClientFile } => candidate.kind === 'code' && !!candidate.clientFile)
      .map((candidate) => candidate.clientFile);
    const selectedDependencyInstalls = candidates
      .filter((candidate): candidate is CodeRunFileCandidate & { dependencyInstall: CodeRunDependencyInstall } => candidate.kind === 'dependency' && !!candidate.dependencyInstall)
      .map((candidate) => candidate.dependencyInstall);
    const selectedAttachments = await selectedClientAttachments(candidates);
    clearRunPollTimer();
    closeRunSocket();
    previewActive = false;
    runSelectionOpen = false;
    runPanelOpen = true;
    runStatus = 'queued';
    runError = null;
    runCancelRequested = false;
    runEvents = [{ kind: 'status', text: 'Queued code run...\n', timestamp: Date.now() / 1000 }];
    runFiles = [];
    try {
      let started;
      try {
        started = await startCodeRun(chatId, embedId, selectedCodeFiles, selectedAttachments, selectedEmbedIds, selectedDependencyInstalls);
      } catch (error) {
        if (!(error instanceof CodeRunStartError) || error.code !== CLIENT_CONTENT_REQUIRED_CODE) {
          throw error;
        }
        runEvents = [
          ...runEvents,
          { kind: 'status', text: 'Recent server cache missed; resending decrypted code from this device...\n', timestamp: Date.now() / 1000 }
        ];
        started = await startCodeRun(chatId, embedId, selectedCodeFiles, selectedAttachments, selectedEmbedIds, selectedDependencyInstalls);
      }
      runExecutionId = started.execution_id;
      persistedRunExecutionId = null;
      runStatus = started.status as CodeRunStatus['status'];
      runFiles = started.files;
      runEvents = [
        { kind: 'status', text: `Queued code run for ${started.target_filename}. Pricing: ${started.credits_per_minute} credits per started minute.\n`, timestamp: Date.now() / 1000 }
      ];
      openRunStream(started.execution_id);
    } catch (error) {
      runStatus = 'failed';
      runError = error instanceof Error ? error.message : 'Code run failed to start';
      runEvents = [{ kind: 'stderr', text: `${runError}\n`, timestamp: Date.now() / 1000 }];
    }
  }

  async function handleCancelRun() {
    if (!runExecutionId || !runActive || runCancelRequested) return;
    runCancelRequested = true;
    try {
      const result = await cancelCodeRun(runExecutionId);
      runStatus = result.status;
      runEvents = [
        ...runEvents,
        { kind: 'status', text: `${$text('app_skills.code.run.cancelling')}\n`, timestamp: Date.now() / 1000 }
      ];
    } catch (error) {
      runCancelRequested = false;
      runError = error instanceof Error ? error.message : 'Code run cancellation failed';
      runEvents = [...runEvents, { kind: 'stderr', text: `${runError}\n`, timestamp: Date.now() / 1000 }];
    }
  }

  $effect(() => {
    if (runExecutionId && TERMINAL_RUN_STATUSES.has(runStatus) && compactRunOutputHasFinalLine()) {
      void persistRunOutput();
    }
  });

  $effect(() => {
    return () => {
      clearRunPollTimer();
      closeRunSocket();
    };
  });

  // Share is handled by UnifiedEmbedFullscreen's built-in share handler
  // which uses currentEmbedId, appId, and skillId to construct the embed
  // share context and properly opens the settings panel (including on mobile).
  
</script>

<!-- 
  Pass BasicInfosBar props to UnifiedEmbedFullscreen for consistent bottom bar
  Code embeds show: filename + line count/language info
-->
<UnifiedEmbedFullscreen
  appId="code"
  skillId="code"
  embedHeaderTitle={skillName}
  embedHeaderSubtitle={statusText || undefined}
  skillIconName={skillIconName}
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  showPIIIncludeOriginal={canIncludeOriginalPII}
  onIncludeOriginalPII={includeOriginalPII}
  skipInitialScrollReset={!!highlightRange}
>
  {#snippet embedHeaderCta()}
    {#if hasCodeHeaderCta}
      <div class="embed-header-cta-group">
        {#if isRunnable && embedId}
          <EmbedHeaderCtaButton label={runCtaLabel} onclick={toggleRunOutput} testId="embed-run-button" />
        {/if}
        {#if isPreviewable}
          <EmbedHeaderCtaButton
            label={previewActive ? $text('app_skills.code.preview_hide') : $text('app_skills.code.preview_show')}
            onclick={togglePreview}
            variant="secondary"
            testId="embed-preview-button"
          />
        {/if}
      </div>
    {/if}
  {/snippet}

  {#snippet content()}
    {#if renderCodeContent}
      <!-- Split-pane layout when preview or terminal output is active, full code otherwise -->
      <div
        class="code-fullscreen-container"
        class:output-pane-active={splitPaneActive}
        class:with-header-cta={hasCodeHeaderCta}
      >
        {#if hasPII}
          <!-- PII reveal toggle bar -->
          <div class="code-pii-bar">
            <button
              data-testid="embed-pii-toggle"
              data-pii-revealed={piiRevealed ? 'true' : 'false'}
              class="pii-toggle-btn"
              class:pii-toggle-active={piiRevealed}
              onclick={togglePII}
              aria-label={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
              title={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
            >
              {#if piiRevealed}
                <!-- Eye-off icon: click to hide -->
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                  <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
                  <line x1="1" y1="1" x2="23" y2="23"/>
                </svg>
              {:else}
                <!-- Eye icon: click to reveal -->
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
              {/if}
              <span class="pii-toggle-label">
                {piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
              </span>
            </button>
          </div>
        {/if}

        <div
          class="code-split-wrapper"
          class:split-active={splitPaneActive}
          class:preview-split-active={outputPaneActive}
          class:code-run-pane-active={codeRunOverlayActive}
        >
          <div
            class="code-panel"
            class:code-panel-split={splitPaneActive}
            class:code-panel-preview-split={outputPaneActive}
            class:code-panel-code-run-split={codeRunOverlayActive}
            data-testid="code-source-panel"
          >
            <div class="code-lines-container" role="presentation" data-testid="code-fullscreen-code" bind:this={codeLinesContainer}>
              {#each highlightedLines as lineHtml, i}
                {@const lineNum = i + 1}
                {@const isHighlighted = highlightRange != null && lineNum >= highlightRange.start && lineNum <= highlightRange.end}
                <div
                  class="code-line"
                  class:code-line--highlighted={isHighlighted}
                  data-line={lineNum}
                >
                  <span class="code-line-gutter" aria-hidden="true">{lineNum}</span>
                  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                  <code class="code-line-text">{@html lineHtml}</code>
                </div>
              {/each}
            </div>
          </div>

          <!-- Preview panel keeps the existing side-by-side rendering behavior. -->
          {#if previewActive}
            <div class="preview-panel">
              <CodePreviewPane code={renderCodeContent} {previewType} />
            </div>
          {/if}

          {#if codeRunOverlayActive}
            <div
              class="code-run-overlay-layer"
              data-testid="code-run-overlay-layer"
              role="presentation"
            >
              <section
                class="code-run-overlay"
                class:code-run-overlay-terminal={runPanelOpen}
                data-testid="code-run-overlay"
                aria-live={runPanelOpen ? 'polite' : undefined}
              >
                <button class="code-run-breadcrumb" data-testid="code-run-view-code" onclick={closeCodeRunOverlay}>
                  <span class="code-run-breadcrumb-chevron" aria-hidden="true"></span>
                  <span>{$text('app_skills.code.run.view_code')}</span>
                </button>

                {#if runSelectionOpen}
                  <section class="code-run-selection" data-testid="code-run-file-selection">
                    <div class="code-run-execute-summary">
                      <div class="code-run-execute-title">{$text('app_skills.code.run.upload_execute')}</div>
                      <div class="code-run-execute-cost">{$text('app_skills.code.run.cost_per_minute')}</div>
                      <button
                        class="code-run-continue"
                        data-testid="code-run-continue"
                        onclick={() => handleRun(selectedRunCandidates)}
                        disabled={runActive || selectedRunCandidates.length === 0}
                      >
                        <span class="code-run-continue-icon" aria-hidden="true"></span>
                        <span>{$text('app_skills.code.run.continue')}</span>
                      </button>
                    </div>

                    {#if runSelectionLoading}
                      <div class="code-run-selection-message">{$text('app_skills.code.run.loading_files')}</div>
                    {:else if runSelectionError}
                      <div class="code-run-selection-message code-run-selection-error">{runSelectionError}</div>
                    {/if}

                    <div class="code-run-selection-groups">
                      <div class="code-run-selection-group">
                        <SettingsSectionHeading title={$text('app_skills.code.run.files')} icon="code" />
                        <div class="code-run-file-list">
                          {#each runCandidates.filter((candidate) => candidate.kind !== 'dependency') as candidate}
                            <button
                              class="code-run-file-option"
                              class:required={candidate.required}
                              data-testid={candidate.required ? 'code-run-required-file-toggle' : 'code-run-optional-file-toggle'}
                              type="button"
                              role="switch"
                              aria-checked={candidate.selected || candidate.required}
                              aria-disabled={candidate.required}
                              disabled={candidate.required}
                              onclick={() => toggleRunCandidate(candidate.id)}
                            >
                              <span class="code-run-file-icon subsetting_icon code" aria-hidden="true"></span>
                              <span class="code-run-file-title">{candidate.title}</span>
                              <span class="code-run-row-spacer"></span>
                              <span class="code-run-row-toggle" aria-hidden="true">
                                <Toggle checked={candidate.selected || candidate.required} disabled={candidate.required} ariaLabel={candidate.title} presentationOnly />
                              </span>
                            </button>
                          {/each}
                        </div>
                      </div>

                      <div class="code-run-selection-group">
                        <SettingsSectionHeading title={$text('app_skills.code.run.packages')} icon="download" />
                        <div class="code-run-file-list">
                          {#each runCandidates.filter((candidate) => candidate.kind === 'dependency') as candidate}
                            <button
                              class="code-run-file-option"
                              data-testid="code-run-optional-file-toggle"
                              type="button"
                              role="switch"
                              aria-checked={candidate.selected}
                              aria-disabled="false"
                              onclick={() => toggleRunCandidate(candidate.id)}
                            >
                              <span class="code-run-file-icon subsetting_icon download" aria-hidden="true"></span>
                              <span class="code-run-file-meta">
                                <span class="code-run-file-title">{candidate.title}</span>
                                {#if candidate.kind === 'dependency' && candidate.dependencyVersionOptions?.length && candidate.selectedVersion}
                                  <span class="code-run-dependency-version-row">
                                    <span>{$text('app_skills.code.run.version')}</span>
                                    <select
                                      value={candidate.selectedVersion}
                                      onclick={(event) => event.stopPropagation()}
                                      onchange={(event) => updateDependencyVersion(candidate.id, (event.currentTarget as HTMLSelectElement).value)}
                                    >
                                      {#each candidate.dependencyVersionOptions as option}
                                        {@const released = formatDependencyReleaseDate(option.released_at)}
                                        <option value={option.version}>{option.version}{released ? ` · ${released}` : ''}</option>
                                      {/each}
                                    </select>
                                  </span>
                                {/if}
                              </span>
                              <span class="code-run-row-spacer"></span>
                              <span class="code-run-row-toggle" aria-hidden="true">
                                <Toggle checked={candidate.selected} ariaLabel={candidate.title} presentationOnly />
                              </span>
                            </button>
                          {:else}
                            <div class="code-run-selection-message">{$text('app_skills.code.run.no_packages')}</div>
                          {/each}
                        </div>
                      </div>
                    </div>

                    {#if selectableRunCandidates.length > 0}
                      <div class="code-run-selection-footer">
                        <button class="code-run-selection-link" type="button" onclick={toggleAllOptionalCandidates}>
                          {allOptionalCandidatesSelected ? $text('app_skills.code.run.unselect_all') : $text('app_skills.code.run.select_all')}
                        </button>
                      </div>
                    {/if}
                  </section>
                {:else if runPanelOpen}
                  <section class="code-run-terminal" data-testid="code-run-terminal" aria-live="polite">
                    <pre class="code-run-output">{#each runDisplayEvents as event}<span class={`code-run-line code-run-${event.kind}`}>{event.text}</span>{/each}</pre>
                    <div class="code-run-terminal-divider"></div>
                    <div class="code-run-terminal-actions" data-testid="code-run-terminal-actions">
                      {#if runActive}
                        <button
                          class="code-run-terminal-action"
                          type="button"
                          aria-label={runCancelRequested ? $text('app_skills.code.run.cancelling_button') : $text('app_skills.code.run.stop')}
                          onclick={handleCancelRun}
                          disabled={!runActive || runCancelRequested}
                        >
                          &gt; {runCancelRequested ? $text('app_skills.code.run.cancelling_button') : $text('app_skills.code.run.stop')}
                        </button>
                      {/if}
                      <button
                        class="code-run-terminal-action"
                        data-testid="code-run-action-ask-followup"
                        type="button"
                        aria-label={$text('app_skills.code.run.ask_followup')}
                        onclick={handleAskRunOutputFollowup}
                        disabled={!hasProgramRunOutput}
                      >
                        &gt; {$text('app_skills.code.run.ask_followup')}
                      </button>
                      <button
                        class="code-run-terminal-action"
                        data-testid="code-run-action-copy-output"
                        type="button"
                        aria-label={$text('app_skills.code.run.copy_output')}
                        onclick={handleCopyRunOutput}
                        disabled={!hasProgramRunOutput}
                      >
                        &gt; {$text('app_skills.code.run.copy_output')}
                      </button>
                      <button
                        class="code-run-terminal-action"
                        data-testid="code-run-action-run-again"
                        type="button"
                        aria-label={$text('app_skills.code.run.again')}
                        onclick={() => handleRun()}
                        disabled={runActive}
                      >
                        &gt; {$text('app_skills.code.run.again')}
                      </button>
                    </div>
                  </section>
                {/if}
              </section>
            </div>
          {/if}
        </div>
      </div>
    {:else}
      <!-- Empty state -->
      <div class="empty-state">
        <p>No code content available.</p>
      </div>
    {/if}

    <!-- Version timeline (shown when embed has been edited via diff) -->
    {#if embedId && versionNumber > 1}
      <EmbedVersionTimeline
        {embedId}
        currentVersion={versionNumber}
        currentContent={latestCodeContent}
        buildRestoredContent={(content, newVersion) => ({ ...dc, code: content, version_number: newVersion })}
        onVersionSelect={(version, content) => {
          includedOriginalCodeContent = content;
          console.log('[CodeEmbedFullscreen] Version selected:', version);
        }}
      />
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* Code fullscreen container */
  .code-fullscreen-container {
    width: calc(100% - 10px);
    background-color: var(--color-grey-15);
    margin-top: 15px;
    padding-bottom: var(--spacing-8);
    margin-left: var(--spacing-5);
    margin-right: var(--spacing-5);
  }

  .code-fullscreen-container.with-header-cta {
    margin-top: 42px;
  }

  /* When preview or terminal output is active, container fills available height.
     Uses flex: 1 instead of height: calc() because the parent .content-area
     is itself a flex child (flex: 1) — percentage heights don't resolve
     against flex-sized parents. */
  .code-fullscreen-container.output-pane-active {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 358px);
    min-height: 0;
    overflow: hidden;
    padding-bottom: 0;
  }

  /* ── Split wrapper — holds code panel + output panel side by side ── */
  .code-split-wrapper {
    width: 100%;
    flex: 1;
    min-height: 0;
  }

  .code-split-wrapper.split-active {
    display: flex;
    gap: 1px;
    background-color: var(--color-grey-20);
    overflow: hidden;
  }

  /* Desktop: 30/70 horizontal split — code narrow, preview wide */
  .code-panel {
    width: 100%;
    overflow: auto;
  }

  .code-panel.code-panel-split {
    min-width: 0;
    overflow: auto;
    background-color: var(--color-grey-15);
  }

  .code-panel.code-panel-preview-split {
    width: 30%;
    flex: 0 0 30%;
  }

  .code-panel.code-panel-code-run-split {
    display: none;
  }

  .preview-panel {
    width: 70%;
    flex: 0 0 70%;
    overflow: hidden;
    background-color: var(--color-grey-15);
    /* position: relative so child can use absolute positioning to fill the panel
       without expanding it to the iframe's content height */
    position: relative;
  }

  .code-run-overlay-layer {
    flex: 1 1 auto;
    min-width: 0;
    height: 100%;
    display: flex;
    align-items: stretch;
    justify-content: center;
    padding: var(--spacing-8) var(--spacing-8) var(--spacing-10);
    overflow: hidden;
  }

  .code-run-overlay {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    box-sizing: border-box;
    border-radius: 2rem;
    background: var(--color-grey-0);
    color: var(--color-grey-100);
    box-shadow: 0 8px 10px rgba(0, 0, 0, 0.22), 0 24px 44px rgba(0, 0, 0, 0.28);
    padding: var(--spacing-6) var(--spacing-8) var(--spacing-8);
  }

  .code-run-overlay-terminal {
    background: var(--color-grey-0);
    color: var(--color-grey-100);
  }

  .code-run-breadcrumb {
    display: inline-flex;
    flex: 0 0 auto;
    align-self: flex-start;
    align-items: center;
    gap: var(--spacing-3);
    min-width: 0;
    height: auto;
    margin: 0 0 var(--spacing-8);
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    filter: none;
    color: var(--color-grey-70);
    font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .code-run-breadcrumb:hover,
  .code-run-breadcrumb:focus-visible {
    background: transparent;
    color: var(--color-grey-100);
    scale: 1;
  }

  .code-run-breadcrumb-chevron {
    width: 1rem;
    height: 1rem;
    border-left: 0.2rem solid currentColor;
    border-bottom: 0.2rem solid currentColor;
    transform: rotate(45deg);
  }

  .code-run-selection {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8);
    min-height: 0;
    overflow: auto;
  }

  .code-run-execute-summary {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    text-align: center;
  }

  .code-run-execute-title {
    color: var(--color-grey-100);
    font-size: var(--font-size-p);
    font-weight: 800;
  }

  .code-run-execute-cost {
    color: var(--color-grey-70);
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .code-run-continue {
    gap: var(--spacing-5);
    margin: var(--spacing-4) 0 0;
    min-width: 18rem;
    color: var(--color-font-button);
    font-weight: 800;
  }

  .code-run-continue-icon {
    width: 1.4rem;
    height: 1.4rem;
    flex: 0 0 auto;
    background: currentColor;
    mask: url('/icons/play.svg') center / contain no-repeat;
    -webkit-mask: url('/icons/play.svg') center / contain no-repeat;
  }

  .code-run-selection-groups {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8);
  }

  .code-run-selection-group :global(.settings-section-heading) {
    padding: 0;
    margin: 0 0 var(--spacing-4);
  }

  .code-run-selection-group :global(.heading-text) {
    color: var(--color-grey-100);
  }

  .code-run-file-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .code-run-file-option {
    display: flex;
    align-items: center;
    width: 100%;
    min-width: 0;
    height: auto;
    min-height: 3.5rem;
    margin: 0;
    padding: var(--spacing-2) 0;
    border: 0;
    border-radius: var(--radius-3);
    background: transparent;
    box-shadow: none;
    filter: none;
    color: var(--color-grey-100);
    text-align: left;
  }

  .code-run-file-option:hover,
  .code-run-file-option:focus-visible {
    background: rgba(255, 255, 255, 0.08);
    scale: 1;
  }

  .code-run-file-option:disabled {
    opacity: 1;
    cursor: default;
  }

  .code-run-file-icon {
    width: 2.75rem;
    height: 2.75rem;
    min-width: 2.75rem;
    margin-right: var(--spacing-6);
  }

  .code-run-file-meta {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    min-width: 0;
  }

  .code-run-file-title {
    min-width: 0;
    overflow: hidden;
    color: #9eb2ff;
    font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: var(--font-size-p);
    font-weight: 800;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .code-run-row-spacer {
    flex: 1 1 auto;
    min-width: var(--spacing-4);
  }

  .code-run-row-toggle {
    display: inline-flex;
    pointer-events: none;
  }

  .code-run-dependency-version-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    color: var(--color-grey-70);
    font-size: var(--font-size-xxs);
  }

  .code-run-dependency-version-row select {
    max-width: 240px;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-1);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    padding: var(--spacing-1) var(--spacing-2);
    font: inherit;
  }

  .code-run-selection-message {
    color: var(--color-grey-70);
    font-size: var(--font-size-small);
  }

  .code-run-selection-error {
    color: var(--color-error, #dc2626);
  }

  .code-run-selection-footer {
    display: flex;
    justify-content: center;
  }

  .code-run-selection-link {
    height: auto;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    filter: none;
    color: var(--color-grey-70);
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .code-run-selection-link:hover,
  .code-run-selection-link:focus-visible {
    background: transparent;
    color: var(--color-grey-100);
    scale: 1;
  }

  .code-run-terminal {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    height: auto;
    min-height: 0;
  }

  .code-run-output {
    flex: 1;
    margin: 0;
    padding: var(--spacing-4) 0 var(--spacing-8);
    min-height: 0;
    overflow: auto;
    white-space: pre-wrap;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.95rem;
    font-weight: 700;
    line-height: 1.55;
    background: transparent;
    color: var(--color-grey-100);
  }

  .code-run-terminal-divider {
    height: 1px;
    margin: 0 0 var(--spacing-5);
    background: #8d8d8d;
  }

  .code-run-terminal-actions {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-2);
  }

  .code-run-terminal-action {
    height: auto;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    filter: none;
    color: var(--color-grey-70);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.95rem;
    font-weight: 800;
    line-height: 1.2;
  }

  .code-run-terminal-action:hover,
  .code-run-terminal-action:focus-visible,
  .code-run-terminal-action:active {
    background: transparent;
    color: var(--color-grey-100);
    scale: 1;
  }

  .code-run-terminal-action:disabled {
    color: #707070;
    opacity: 1;
    cursor: not-allowed;
  }

  .code-run-line {
    display: inline;
  }

  .code-run-status {
    color: #7dd3fc;
  }

  .code-run-stderr {
    color: #fca5a5;
  }

  @container fullscreen (min-width: 1400px) {
    .code-split-wrapper.code-run-pane-active {
      gap: var(--spacing-8);
      background-color: transparent;
    }

    .code-panel.code-panel-code-run-split {
      display: block;
      width: 50%;
      flex: 1 1 50%;
    }

    .code-run-pane-active .code-run-overlay-layer {
      flex: 1 1 50%;
      padding: 0 var(--spacing-8) var(--spacing-8) 0;
    }
  }

  /* Mobile: preview only — hide code panel, show full-width preview.
     The user can toggle the preview button off to see code again. */
  @media (max-width: 768px) {
    .code-panel.code-panel-split {
      display: none;
    }

    .preview-panel {
      width: 100%;
      flex: 1 1 auto;
      min-height: 0;
    }

    .code-run-overlay-layer {
      align-items: flex-start;
      padding: var(--spacing-6) var(--spacing-3) var(--spacing-8);
    }

    .code-run-overlay {
      width: 100%;
      max-height: min(32rem, calc(100vh - 16rem));
      border-radius: 1.75rem;
      padding: var(--spacing-5) var(--spacing-5) var(--spacing-6);
    }

    .code-run-continue {
      min-width: min(16rem, 100%);
    }

    .code-run-file-title {
      font-size: var(--font-size-small);
    }
  }

  /* PII toggle bar — shown above the code when PII mappings exist */
  .code-pii-bar {
    display: flex;
    align-items: center;
    padding: 6px 0 8px;
  }

  .pii-toggle-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    padding: 5px 12px;
    border-radius: var(--radius-2);
    border: none;
    background: var(--color-grey-25);
    color: var(--color-font-secondary);
    cursor: pointer;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    transition: background-color var(--duration-fast), color var(--duration-fast);
  }

  .pii-toggle-btn:hover {
    background: var(--color-grey-30);
    color: var(--color-font-primary);
  }

  .pii-toggle-btn.pii-toggle-active {
    background: var(--color-warning-subtle, rgba(255, 165, 0, 0.15));
    color: var(--color-warning, #e07b00);
  }

  .pii-toggle-btn.pii-toggle-active:hover {
    background: var(--color-warning-subtle-hover, rgba(255, 165, 0, 0.25));
  }

  .pii-toggle-label {
    font-size: var(--font-size-xxs);
  }

  /* Per-line container — vertical stack of .code-line rows.
     overflow-x on the container allows horizontal scrolling for long lines
     while keeping line highlighting at the full container width. */
  .code-lines-container {
    width: 100%;
    overflow-x: auto;
    font-size: var(--font-size-small);
    line-height: 1.6;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    -webkit-text-size-adjust: 100%;
    text-size-adjust: 100%;
  }

  /* Each line row: gutter number on the left, code text on the right. */
  .code-line {
    display: flex;
    align-items: baseline;
    min-width: max-content; /* prevents line from wrapping when container scrolls */
    position: relative;
    -webkit-text-size-adjust: 100%;
    text-size-adjust: 100%;
  }

  /* GitHub-style line highlight — full-width yellow background bar.
     Applied to every line inside the requested range. */
  .code-line--highlighted {
    background-color: rgba(255, 200, 50, 0.18);
    border-left: 2px solid rgba(255, 200, 50, 0.7);
  }

  /* Gutter: right-aligned line numbers, not selectable. */
  .code-line-gutter {
    flex: 0 0 auto;
    min-width: 40px;
    padding-right: var(--spacing-6);
    text-align: right;
    color: var(--color-font-tertiary);
    user-select: none;
    -webkit-user-select: none;
    font-size: inherit;
    line-height: inherit;
    font-family: inherit;
  }

  /* Code text: allows text selection, no wrapping (container scrolls instead). */
  .code-line-text {
    flex: 1 1 auto;
    display: block;
    white-space: pre;
    color: var(--color-font-primary);
    background: transparent;
    padding: 0;
    margin: 0;
    font-size: inherit;
    line-height: inherit;
    font-family: inherit;
    user-select: text;
    -webkit-user-select: text;
    -webkit-text-size-adjust: 100%;
    text-size-adjust: 100%;
  }

  .code-line-text :global(span) {
    font-family: inherit;
    font-size: inherit;
    line-height: inherit;
  }

  /* Syntax highlighting colors — delegated to highlight.js github-dark theme spans */
  .code-line-text :global(.keyword) {
    color: var(--color-syntax-keyword, #c678dd);
  }

  .code-line-text :global(.string) {
    color: var(--color-syntax-string, #98c379);
  }

  .code-line-text :global(.comment) {
    color: var(--color-syntax-comment, #5c6370);
  }

  .code-line-text :global(.function) {
    color: var(--color-syntax-function, #61afef);
  }

  .code-line-text :global(.number) {
    color: var(--color-syntax-number, #d19a66);
  }
  
  /* Empty state */
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
</style>
