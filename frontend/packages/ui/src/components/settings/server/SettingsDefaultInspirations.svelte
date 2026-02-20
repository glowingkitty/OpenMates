<!--
    Settings Default Inspirations Component (Admin only)

    Allows admins to manage user-suggested videos that may become published
    Default Daily Inspirations shown on the new-chat screen.

    Workflow per suggestion card:
      1. pending_approval  → Admin clicks "Generate Content" → Gemini generates phrase + category
      2. generating        → AI is working (WS event: default_inspiration_updated)
      3. pending_review    → Admin reviews/edits phrase, category → clicks "Accept"
      4. translating       → Translation task runs (WS events: default_inspiration_progress)
      5. published         → Live, visible to all users

    Follows the exact pattern of SettingsCommunitySuggestions.svelte:
      - Svelte 5 runes ($state, $derived)
      - webSocketService.on/off for WS events
      - Progress bar for translation
      - Admin-only English UI (no i18n required)
-->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { getApiEndpoint } from '@repo/ui';
    import { webSocketService } from '../../../services/websocketService';

    const dispatch = createEventDispatcher();

    // ─── Types ────────────────────────────────────────────────────────────────

    interface InspirationSuggestion {
        id: string;
        status: string;
        video_id: string;
        video_title: string;
        video_url: string;
        video_thumbnail: string;
        channel_name: string | null;
        view_count: number | null;
        duration_seconds: number | null;
        published_at: string | null;
        category: string | null;
        phrase: string | null;
        assistant_response: string | null;
        created_at: string;
        approved_at: string | null;
    }

    interface InspirationUpdatePayload {
        user_id?: string;
        inspiration_id: string;
        status: string;
        category?: string;
        phrase?: string;
        assistant_response?: string;
    }

    interface InspirationProgressPayload {
        user_id?: string;
        inspiration_id: string;
        stage: string;
        progress_percentage?: number;
        current_language?: string;
        message?: string;
    }

    interface TranslationProgress {
        stage: string;
        progress_percentage: number;
        current_language: string;
        message: string;
        last_update: number;
    }

    // ─── State ────────────────────────────────────────────────────────────────

    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let suggestions = $state<InspirationSuggestion[]>([]);
    let publishedInspirations = $state<InspirationSuggestion[]>([]);
    let isSubmitting = $state(false);

    // Translation progress tracked per inspiration_id
    let translationProgress = $state<Map<string, TranslationProgress>>(new Map());

    // Editable fields per card (keyed by inspiration_id)
    let editablePhrase = $state<Map<string, string>>(new Map());
    let editableCategory = $state<Map<string, string>>(new Map());
    let editableAssistantResponse = $state<Map<string, string>>(new Map());

    const MAX_PUBLISHED = 3;

    // ─── Data Loading ─────────────────────────────────────────────────────────

    async function loadSuggestions() {
        try {
            isLoading = true;
            error = null;

            const response = await fetch(getApiEndpoint('/v1/admin/default-inspirations'), {
                credentials: 'include'
            });

            if (!response.ok) {
                if (response.status === 403) {
                    error = 'Admin privileges required to view daily inspiration suggestions.';
                } else {
                    error = 'Failed to load daily inspiration suggestions.';
                }
                return;
            }

            const data = await response.json();
            const all: InspirationSuggestion[] = data.inspirations || [];

            // Split into pending/generating/review/failed vs published/translating
            publishedInspirations = all.filter(i =>
                i.status === 'published' || i.status === 'translating'
            );
            suggestions = all.filter(i =>
                i.status !== 'published' && i.status !== 'translating'
            );

            // Initialize editable fields for pending_review cards
            for (const s of suggestions) {
                if (s.status === 'pending_review') {
                    if (!editablePhrase.has(s.id)) {
                        editablePhrase.set(s.id, s.phrase || '');
                    }
                    if (!editableCategory.has(s.id)) {
                        editableCategory.set(s.id, s.category || '');
                    }
                    if (!editableAssistantResponse.has(s.id)) {
                        editableAssistantResponse.set(s.id, s.assistant_response || '');
                    }
                }
            }
            editablePhrase = new Map(editablePhrase);
            editableCategory = new Map(editableCategory);
            editableAssistantResponse = new Map(editableAssistantResponse);

        } catch (err) {
            console.error('[SettingsDefaultInspirations] Error loading suggestions:', err);
            error = 'Failed to connect to server.';
        } finally {
            isLoading = false;
        }
    }

    // ─── Actions ──────────────────────────────────────────────────────────────

    /** Trigger AI content generation for a pending_approval suggestion */
    async function generateContent(inspirationId: string) {
        try {
            isSubmitting = true;

            const response = await fetch(
                getApiEndpoint(`/v1/admin/default-inspirations/${inspirationId}/generate`),
                {
                    method: 'POST',
                    credentials: 'include'
                }
            );

            if (!response.ok) {
                const data = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(data.detail || 'Failed to start content generation');
            }

            // Optimistically update status to 'generating'
            updateSuggestionStatus(inspirationId, 'generating');

            dispatch('showToast', {
                type: 'success',
                message: 'Content generation started...'
            });
        } catch (err) {
            console.error('[SettingsDefaultInspirations] Error generating content:', err);
            dispatch('showToast', {
                type: 'error',
                message: err instanceof Error ? err.message : 'Failed to generate content'
            });
        } finally {
            isSubmitting = false;
        }
    }

    /** Accept a pending_review suggestion and trigger translation */
    async function confirmInspiration(inspirationId: string) {
        try {
            isSubmitting = true;

            const phrase = editablePhrase.get(inspirationId) || '';
            const category = editableCategory.get(inspirationId) || '';
            const assistantResponse = editableAssistantResponse.get(inspirationId) || '';

            if (!phrase.trim()) {
                dispatch('showToast', { type: 'error', message: 'Phrase cannot be empty' });
                return;
            }

            const response = await fetch(
                getApiEndpoint(`/v1/admin/default-inspirations/${inspirationId}/confirm`),
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ phrase, category, assistant_response: assistantResponse })
                }
            );

            if (!response.ok) {
                const data = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(data.detail || 'Failed to confirm inspiration');
            }

            // Move to translating — optimistically add to publishedInspirations list
            const suggestion = suggestions.find(s => s.id === inspirationId);
            if (suggestion) {
                suggestions = suggestions.filter(s => s.id !== inspirationId);
                publishedInspirations = [...publishedInspirations, {
                    ...suggestion,
                    status: 'translating',
                    phrase,
                    category,
                    assistant_response: assistantResponse
                }];
            }

            dispatch('showToast', {
                type: 'success',
                message: 'Accepted! Translation in progress...'
            });
        } catch (err) {
            console.error('[SettingsDefaultInspirations] Error confirming inspiration:', err);
            dispatch('showToast', {
                type: 'error',
                message: err instanceof Error ? err.message : 'Failed to confirm inspiration'
            });
        } finally {
            isSubmitting = false;
        }
    }

    /** Delete a suggestion or remove a published inspiration */
    async function deleteInspiration(inspirationId: string) {
        if (!confirm('Are you sure you want to delete this inspiration? This cannot be undone.')) {
            return;
        }

        // Optimistically remove from UI
        const fromSuggestions = suggestions.find(s => s.id === inspirationId);
        const fromPublished = publishedInspirations.find(i => i.id === inspirationId);

        if (fromSuggestions) {
            suggestions = suggestions.filter(s => s.id !== inspirationId);
        }
        if (fromPublished) {
            publishedInspirations = publishedInspirations.filter(i => i.id !== inspirationId);
        }

        try {
            isSubmitting = true;

            const response = await fetch(
                getApiEndpoint(`/v1/admin/default-inspirations/${inspirationId}`),
                {
                    method: 'DELETE',
                    credentials: 'include'
                }
            );

            if (!response.ok) {
                throw new Error('Failed to delete inspiration');
            }

            dispatch('showToast', { type: 'success', message: 'Inspiration deleted.' });
        } catch (err) {
            console.error('[SettingsDefaultInspirations] Error deleting inspiration:', err);

            // Restore on failure
            if (fromSuggestions) {
                suggestions = [...suggestions, fromSuggestions];
            }
            if (fromPublished) {
                publishedInspirations = [...publishedInspirations, fromPublished];
            }

            dispatch('showToast', {
                type: 'error',
                message: 'Failed to delete inspiration'
            });
        } finally {
            isSubmitting = false;
        }
    }

    // ─── WebSocket Handlers ───────────────────────────────────────────────────

    function handleInspirationUpdate(payload: InspirationUpdatePayload) {
        console.log('[SettingsDefaultInspirations] Received default_inspiration_updated:', payload);
        const { inspiration_id, status, category, phrase, assistant_response } = payload;

        // Update in suggestions list
        const idx = suggestions.findIndex(s => s.id === inspiration_id);
        if (idx !== -1) {
            suggestions[idx] = {
                ...suggestions[idx],
                status,
                ...(category !== undefined && { category }),
                ...(phrase !== undefined && { phrase }),
                ...(assistant_response !== undefined && { assistant_response })
            };
            suggestions = [...suggestions];

            // Initialize editable fields when AI content arrives
            if (status === 'pending_review') {
                editablePhrase.set(inspiration_id, phrase || suggestions[idx].phrase || '');
                editableCategory.set(inspiration_id, category || suggestions[idx].category || '');
                editableAssistantResponse.set(inspiration_id, assistant_response || suggestions[idx].assistant_response || '');
                editablePhrase = new Map(editablePhrase);
                editableCategory = new Map(editableCategory);
                editableAssistantResponse = new Map(editableAssistantResponse);
            }

            if (status === 'generation_failed') {
                dispatch('showToast', { type: 'error', message: 'Content generation failed.' });
            }
        }

        // Update in published list
        const pubIdx = publishedInspirations.findIndex(i => i.id === inspiration_id);
        if (pubIdx !== -1) {
            publishedInspirations[pubIdx] = {
                ...publishedInspirations[pubIdx],
                status,
                ...(category !== undefined && { category }),
                ...(phrase !== undefined && { phrase }),
                ...(assistant_response !== undefined && { assistant_response })
            };
            publishedInspirations = [...publishedInspirations];

            if (status === 'published') {
                dispatch('showToast', {
                    type: 'success',
                    message: 'Inspiration published and live!'
                });
            } else if (status === 'translation_failed') {
                dispatch('showToast', { type: 'error', message: 'Translation failed.' });
            }
        }
    }

    function handleInspirationProgress(payload: InspirationProgressPayload) {
        console.log('[SettingsDefaultInspirations] Received default_inspiration_progress:', payload);
        const { inspiration_id, stage, progress_percentage, current_language, message } = payload;

        const existing = translationProgress.get(inspiration_id);
        const newPct = progress_percentage || 0;
        const effectivePct = existing
            ? Math.max(existing.progress_percentage, newPct)
            : newPct;

        translationProgress.set(inspiration_id, {
            stage,
            progress_percentage: effectivePct,
            current_language: current_language || '',
            message: message || 'Processing...',
            last_update: Date.now()
        });
        translationProgress = new Map(translationProgress);
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────

    function updateSuggestionStatus(inspirationId: string, status: string) {
        const idx = suggestions.findIndex(s => s.id === inspirationId);
        if (idx !== -1) {
            suggestions[idx] = { ...suggestions[idx], status };
            suggestions = [...suggestions];
        }
    }

    function formatDate(dateString: string): string {
        try {
            return new Date(dateString).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return 'Unknown date';
        }
    }

    function formatDuration(seconds: number | null): string {
        if (seconds === null) return '';
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m}:${String(s).padStart(2, '0')}`;
    }

    function getProgressInfo(inspirationId: string): TranslationProgress | undefined {
        return translationProgress.get(inspirationId);
    }

    function statusLabel(status: string): string {
        const labels: Record<string, string> = {
            pending_approval: 'Pending',
            generating: 'Generating...',
            pending_review: 'Review needed',
            translating: 'Translating...',
            published: 'Published',
            generation_failed: 'Generation failed',
            translation_failed: 'Translation failed'
        };
        return labels[status] || status;
    }

    // ─── Lifecycle ────────────────────────────────────────────────────────────

    onMount(() => {
        loadSuggestions();
        webSocketService.on('default_inspiration_updated', handleInspirationUpdate);
        webSocketService.on('default_inspiration_progress', handleInspirationProgress);
    });

    onDestroy(() => {
        webSocketService.off('default_inspiration_updated', handleInspirationUpdate);
        webSocketService.off('default_inspiration_progress', handleInspirationProgress);
    });
</script>

<div class="default-inspirations">
    <!-- Header -->
    <div class="header">
        <h2>Default Daily Inspirations</h2>
        <p>Review and publish video suggestions submitted by users. Up to {MAX_PUBLISHED} inspirations can be published at a time.</p>
    </div>

    <!-- Published Inspirations Section -->
    <div class="section">
        <div class="section-header">
            <h3>Published ({publishedInspirations.length}/{MAX_PUBLISHED})</h3>
        </div>

        {#if publishedInspirations.length === 0}
            <div class="empty-state">
                <div class="empty-icon">✨</div>
                <p>No published inspirations yet</p>
            </div>
        {:else}
            <div class="cards-grid">
                {#each publishedInspirations as item}
                    <div class="inspiration-card">
                        <!-- Thumbnail -->
                        {#if item.video_thumbnail}
                            <div class="video-thumbnail">
                                <img src={item.video_thumbnail} alt={item.video_title} />
                            </div>
                        {/if}

                        <div class="card-header">
                            <h4>{item.video_title || 'Untitled'}</h4>
                            <span class="status-tag status-{item.status}">
                                {statusLabel(item.status)}
                            </span>
                        </div>

                        {#if item.channel_name}
                            <p class="channel-name">{item.channel_name}{item.duration_seconds ? ` • ${formatDuration(item.duration_seconds)}` : ''}</p>
                        {/if}

                        <!-- Translation Progress Bar -->
                        {#if item.status === 'translating'}
                            {@const progress = getProgressInfo(item.id)}
                            <div class="translation-progress">
                                <div class="progress-bar-container">
                                    <div
                                        class="progress-bar-fill"
                                        style="width: {progress?.progress_percentage || 0}%"
                                    ></div>
                                </div>
                                <div class="progress-info">
                                    <span class="progress-text">{progress?.message || 'Starting...'}</span>
                                    <span class="progress-percentage">{progress?.progress_percentage || 0}%</span>
                                </div>
                                {#if progress?.current_language}
                                    <div class="progress-languages">Translating: {progress.current_language.toUpperCase()}</div>
                                {/if}
                            </div>
                        {/if}

                        {#if item.phrase}
                            <p class="phrase-text">"{item.phrase}"</p>
                        {/if}

                        {#if item.category}
                            <span class="category-tag">{item.category}</span>
                        {/if}

                        <div class="card-footer">
                            <span class="date-text">{formatDate(item.created_at)}</span>
                            <button
                                onclick={() => deleteInspiration(item.id)}
                                class="btn btn-danger btn-small"
                                disabled={isSubmitting}
                            >
                                Remove
                            </button>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <!-- Pending Suggestions Section -->
    <div class="section">
        <div class="section-header">
            <h3>Pending Suggestions</h3>
            <span class="count-info">{suggestions.length} suggestion{suggestions.length !== 1 ? 's' : ''}</span>
        </div>

        {#if isLoading}
            <div class="loading">
                <div class="spinner"></div>
                <p>Loading suggestions...</p>
            </div>
        {:else if error}
            <div class="error">
                <div class="error-icon">⚠️</div>
                <p>{error}</p>
                <button onclick={loadSuggestions} class="btn btn-primary">Try Again</button>
            </div>
        {:else if suggestions.length === 0}
            <div class="empty-state">
                <div class="empty-icon">📝</div>
                <p>No pending suggestions</p>
                <span class="empty-subtext">
                    When users suggest videos as daily inspirations, they will appear here.
                </span>
            </div>
        {:else}
            <div class="cards-grid">
                {#each suggestions as item}
                    <div class="inspiration-card">
                        <!-- Thumbnail -->
                        {#if item.video_thumbnail}
                            <div class="video-thumbnail">
                                <img src={item.video_thumbnail} alt={item.video_title} />
                            </div>
                        {/if}

                        <div class="card-header">
                            <h4>{item.video_title || 'Untitled'}</h4>
                            <span class="status-tag status-{item.status}">
                                {statusLabel(item.status)}
                            </span>
                        </div>

                        {#if item.channel_name}
                            <p class="channel-name">{item.channel_name}{item.duration_seconds ? ` • ${formatDuration(item.duration_seconds)}` : ''}</p>
                        {/if}

                        {#if item.video_url}
                            <a
                                href={item.video_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                class="video-link"
                            >
                                Watch on YouTube ↗
                            </a>
                        {/if}

                        <!-- Editable fields (pending_review state) -->
                        {#if item.status === 'pending_review'}
                            <div class="editable-fields">
                                <label class="field-label">
                                    Category
                                    <input
                                        type="text"
                                        class="field-input"
                                        value={editableCategory.get(item.id) || ''}
                                        oninput={(e) => {
                                            editableCategory.set(item.id, e.currentTarget.value);
                                            editableCategory = new Map(editableCategory);
                                        }}
                                        placeholder="e.g. science, history, technology"
                                    />
                                </label>
                                <label class="field-label">
                                    CTA Phrase
                                    <input
                                        type="text"
                                        class="field-input"
                                        value={editablePhrase.get(item.id) || ''}
                                        oninput={(e) => {
                                            editablePhrase.set(item.id, e.currentTarget.value);
                                            editablePhrase = new Map(editablePhrase);
                                        }}
                                        placeholder="Short call-to-action phrase..."
                                    />
                                </label>
                                <label class="field-label">
                                    Assistant Response
                                    <textarea
                                        class="field-textarea"
                                        value={editableAssistantResponse.get(item.id) || ''}
                                        oninput={(e) => {
                                            editableAssistantResponse.set(item.id, e.currentTarget.value);
                                            editableAssistantResponse = new Map(editableAssistantResponse);
                                        }}
                                        placeholder="Initial assistant message to show in the chat..."
                                        rows={3}
                                    ></textarea>
                                </label>
                            </div>
                        {:else if item.status === 'generating'}
                            <div class="generating-info">
                                <div class="spinner spinner-small"></div>
                                <span>AI is generating content...</span>
                            </div>
                        {:else if item.status === 'generation_failed'}
                            <p class="error-text">Content generation failed. Try again.</p>
                        {/if}

                        <!-- Actions -->
                        <div class="card-actions">
                            <span class="date-text">{formatDate(item.created_at)}</span>
                            <div class="action-buttons">
                                <button
                                    onclick={() => deleteInspiration(item.id)}
                                    class="btn btn-danger btn-small"
                                    disabled={isSubmitting}
                                >
                                    Delete
                                </button>
                                {#if item.status === 'pending_approval' || item.status === 'generation_failed'}
                                    <button
                                        onclick={() => generateContent(item.id)}
                                        class="btn btn-secondary btn-small"
                                        disabled={isSubmitting}
                                    >
                                        Generate Content
                                    </button>
                                {:else if item.status === 'pending_review'}
                                    <button
                                        onclick={() => confirmInspiration(item.id)}
                                        class="btn btn-primary btn-small"
                                        disabled={isSubmitting || !editablePhrase.get(item.id)?.trim()}
                                    >
                                        Accept
                                    </button>
                                {/if}
                            </div>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <!-- Info Section -->
    <div class="info-section">
        <div class="info-card">
            <h4>How it works</h4>
            <ul>
                <li>Users can suggest YouTube video embeds as daily inspirations when sharing them</li>
                <li>Click "Generate Content" to let Gemini create a CTA phrase, category, and assistant response</li>
                <li>Review and edit the generated content, then click "Accept" to publish</li>
                <li>Accepted inspirations are translated into all supported languages automatically</li>
                <li>Maximum {MAX_PUBLISHED} published inspirations at any time — oldest is removed when adding a 4th</li>
                <li>Published inspirations appear in the Daily Inspiration banner for all users</li>
            </ul>
        </div>
    </div>
</div>

<style>
    .default-inspirations {
        padding: 1.5rem;
        max-width: 1000px;
        margin: 0 auto;
    }

    .header {
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--color-border);
    }

    .header p {
        margin: 0;
        color: var(--color-text-secondary);
    }

    .section {
        margin-bottom: 2rem;
    }

    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
    }

    .section-header h3 {
        margin: 0;
        color: var(--color-text-primary);
    }

    .count-info {
        font-size: 0.9rem;
        color: var(--color-text-secondary);
    }

    .cards-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1rem;
    }

    .inspiration-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .video-thumbnail {
        border-radius: 6px;
        overflow: hidden;
        aspect-ratio: 16 / 9;
        background: var(--color-background-tertiary);
    }

    .video-thumbnail img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 0.5rem;
    }

    .card-header h4 {
        margin: 0;
        flex: 1;
        color: var(--color-text-primary);
        line-height: 1.3;
        font-size: 0.95rem;
    }

    .channel-name {
        font-size: 0.85rem;
        color: var(--color-text-secondary);
        margin: 0;
    }

    .video-link {
        font-size: 0.85rem;
        color: var(--color-primary);
        text-decoration: none;
    }

    .video-link:hover {
        text-decoration: underline;
    }

    .phrase-text {
        font-style: italic;
        color: var(--color-text-secondary);
        font-size: 0.9rem;
        margin: 0;
        line-height: 1.4;
    }

    .category-tag {
        display: inline-block;
        background: var(--color-primary-light);
        color: var(--color-primary);
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 500;
        width: fit-content;
    }

    .status-tag {
        padding: 0.2rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        white-space: nowrap;
        flex-shrink: 0;
    }

    .status-pending_approval {
        background: var(--color-background-tertiary);
        color: var(--color-text-secondary);
    }

    .status-generating {
        background: #FEF3C7;
        color: #92400E;
    }

    .status-pending_review {
        background: #DBEAFE;
        color: #1E40AF;
    }

    .status-translating {
        background: #FEF3C7;
        color: #92400E;
    }

    .status-published {
        background: #D1FAE5;
        color: #065F46;
    }

    .status-generation_failed,
    .status-translation_failed {
        background: #FEE2E2;
        color: #991B1B;
    }

    /* Translation Progress Bar */
    .translation-progress {
        padding: 0.75rem;
        background: var(--color-background-tertiary);
        border-radius: 6px;
        border: 1px solid var(--color-border);
    }

    .progress-bar-container {
        width: 100%;
        height: 8px;
        background: var(--color-background-secondary);
        border-radius: 4px;
        overflow: hidden;
        margin-bottom: 0.5rem;
    }

    .progress-bar-fill {
        height: 100%;
        background: linear-gradient(90deg, var(--color-primary) 0%, var(--color-primary-light) 100%);
        border-radius: 4px;
        transition: width 0.3s ease-out;
        position: relative;
    }

    .progress-bar-fill::after {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.2) 50%,
            transparent 100%
        );
        animation: shimmer 1.5s infinite;
    }

    @keyframes shimmer {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
    }

    .progress-info {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.8rem;
    }

    .progress-text {
        color: var(--color-text-secondary);
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin-right: 0.5rem;
    }

    .progress-percentage {
        color: var(--color-primary);
        font-weight: 600;
        white-space: nowrap;
    }

    .progress-languages {
        font-size: 0.75rem;
        color: var(--color-text-tertiary);
        margin-top: 0.25rem;
    }

    /* Editable fields */
    .editable-fields {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        padding: 0.75rem;
        background: var(--color-background-tertiary);
        border-radius: 6px;
        border: 1px solid var(--color-border);
    }

    .field-label {
        display: flex;
        flex-direction: column;
        gap: 0.3rem;
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--color-text-primary);
    }

    .field-input {
        padding: 0.4rem 0.6rem;
        border: 1px solid var(--color-border);
        border-radius: 4px;
        background: var(--color-background-secondary);
        color: var(--color-text-primary);
        font-size: 0.9rem;
        width: 100%;
        box-sizing: border-box;
    }

    .field-input:focus,
    .field-textarea:focus {
        outline: none;
        border-color: var(--color-primary);
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
    }

    .field-textarea {
        padding: 0.4rem 0.6rem;
        border: 1px solid var(--color-border);
        border-radius: 4px;
        background: var(--color-background-secondary);
        color: var(--color-text-primary);
        font-size: 0.9rem;
        width: 100%;
        box-sizing: border-box;
        resize: vertical;
        font-family: inherit;
        line-height: 1.4;
    }

    .generating-info {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.9rem;
        color: var(--color-text-secondary);
    }

    .error-text {
        font-size: 0.85rem;
        color: var(--color-error);
        margin: 0;
    }

    .card-footer,
    .card-actions {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: auto;
        gap: 0.5rem;
        flex-wrap: wrap;
    }

    .action-buttons {
        display: flex;
        gap: 0.5rem;
    }

    .date-text {
        font-size: 0.85rem;
        color: var(--color-text-secondary);
        white-space: nowrap;
    }

    /* Buttons */
    .btn {
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: none;
        font-size: 0.9rem;
    }

    .btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .btn-small {
        padding: 0.4rem 0.8rem;
        font-size: 0.85rem;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
    }

    .btn-primary:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .btn-secondary {
        background: var(--color-background-tertiary);
        color: var(--color-text-primary);
        border: 1px solid var(--color-border);
    }

    .btn-secondary:hover:not(:disabled) {
        background: var(--color-background-secondary);
        border-color: var(--color-primary);
    }

    .btn-danger {
        background: var(--color-error);
        color: white;
    }

    .btn-danger:hover:not(:disabled) {
        background: var(--color-error-dark);
    }

    /* Loading / Error / Empty states */
    .loading,
    .error,
    .empty-state {
        text-align: center;
        padding: 2rem;
    }

    .spinner {
        width: 2rem;
        height: 2rem;
        border: 3px solid var(--color-border);
        border-top: 3px solid var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 1rem;
    }

    .spinner-small {
        width: 1rem;
        height: 1rem;
        margin: 0;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .error-icon,
    .empty-icon {
        font-size: 2rem;
        margin-bottom: 0.5rem;
    }

    .empty-subtext {
        display: block;
        margin-top: 0.5rem;
        font-size: 0.9rem;
        color: var(--color-text-tertiary);
    }

    /* Info section */
    .info-section {
        margin-top: 2rem;
        padding-top: 2rem;
        border-top: 1px solid var(--color-border);
    }

    .info-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        padding: 1.5rem;
    }

    .info-card h4 {
        margin: 0 0 1rem 0;
        color: var(--color-text-primary);
    }

    .info-card ul {
        margin: 0;
        padding-left: 1.5rem;
        color: var(--color-text-secondary);
        line-height: 1.6;
    }

    .info-card li {
        margin-bottom: 0.5rem;
    }

    @media (max-width: 768px) {
        .default-inspirations {
            padding: 1rem;
        }

        .cards-grid {
            grid-template-columns: 1fr;
        }

        .section-header {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.5rem;
        }

        .card-actions,
        .card-footer {
            flex-direction: column;
            gap: 0.5rem;
            width: 100%;
        }

        .action-buttons {
            width: 100%;
            flex-direction: column;
        }

        .action-buttons .btn {
            width: 100%;
        }
    }
</style>
