<!--
    ReportIssueComposer — the single free-text field of the Report Issue form
    plus quick actions underneath: attach an image, select a UI element, and
    voice dictation.

    Dictation reuses the realtime transcription overlay from the message input
    (RecordAudio + services/audioRealtimeTranscription.ts) and appends the
    corrected transcript to the text, like WorkspacePromptComposer does.
    Image and element capture stay owned by SettingsReportIssue, which passes
    the handlers in. The actions are compact icon buttons with tooltips.

    Dictation is free for the report form but bounded by the server
    (services/report_issue_dictation_quota.py): two minutes per recording and
    a daily budget per signed-in user. When the budget is spent the record
    button is greyed out with a "try again tomorrow" tooltip. Guests use the
    bounded anonymous allowance instead.

    Preview: /dev/preview/settings/ReportIssueComposer
    Tests: frontend/apps/web_app/tests/report-issue-flow.spec.ts
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text, notificationStore } from '@repo/ui';
    import RecordAudio from '../enter_message/RecordAudio.svelte';
    import InputWarning from '../common/InputWarning.svelte';
    import { SettingsSectionHeading, SettingsTextarea } from './elements';
    import { tooltip } from '../../actions/tooltip';
    import { getApiEndpoint } from '../../config/api';
    import { ReportDictationLimitError, type AudioRealtimeTranscriptionHandle } from '../../services/audioRealtimeTranscription';

    /** Matches REPORT_DICTATION_MAX_RECORDING_SECONDS on the server. */
    const MAX_RECORDING_SECONDS = 120;
    const DICTATION_QUOTA_ENDPOINT = '/v1/apps/audio/report-issue-dictation-quota';

    type RecordedAudio = { realtime?: AudioRealtimeTranscriptionHandle; liveTranscript?: string };

    let {
        value = $bindable(''),
        disabled,
        error,
        anonymous,
        canAttachImage,
        elementPickerActive,
        onAttachImage,
        onPickElement,
    }: {
        value?: string;
        disabled: boolean;
        error: string;
        /** Guests dictate through the anonymous transcription budget. */
        anonymous: boolean;
        /** Image attachments are stored server-side only for signed-in users. */
        canAttachImage: boolean;
        elementPickerActive: boolean;
        onAttachImage: () => void;
        onPickElement: () => void;
    } = $props();

    let recording = $state(false);
    let transcribing = $state(false);
    /** Signed-in users: false once today's free dictation budget is spent. */
    let dictationAvailable = $state(true);
    /** Shorter of the per-recording cap and what is left of today's budget. */
    let maxRecordingSeconds = $state(MAX_RECORDING_SECONDS);

    async function refreshDictationQuota(): Promise<void> {
        if (anonymous) return;
        const response = await fetch(getApiEndpoint(DICTATION_QUOTA_ENDPOINT), { credentials: 'include' });
        if (!response.ok) {
            console.warn('[ReportIssueComposer] Dictation quota unavailable:', response.status);
            return;
        }
        const quota: { available: boolean; remaining_seconds: number; max_recording_seconds: number } = await response.json();
        dictationAvailable = quota.available;
        maxRecordingSeconds = Math.max(1, Math.min(quota.max_recording_seconds || MAX_RECORDING_SECONDS, quota.remaining_seconds));
    }

    onMount(() => {
        void refreshDictationQuota().catch((quotaError) => {
            console.warn('[ReportIssueComposer] Dictation quota request failed:', quotaError);
        });
    });

    function startDictation(): void {
        if (!dictationAvailable) {
            notificationStore.info($text('settings.report_issue.dictation_unavailable_today'), 6000);
            return;
        }
        recording = true;
    }

    function handleTranscriptionError(error: unknown): void {
        recording = false;
        if (error instanceof ReportDictationLimitError && error.code === 'daily_limit') {
            dictationAvailable = false;
            notificationStore.info($text('settings.report_issue.dictation_unavailable_today'), 6000);
            return;
        }
        if (error instanceof ReportDictationLimitError && error.code === 'recording_limit') {
            notificationStore.info($text('settings.report_issue.dictation_recording_limit'), 6000);
            return;
        }
        notificationStore.error($text('settings.report_issue.dictation_failed'), 6000);
    }

    function appendTranscript(transcript: string): void {
        const addition = transcript.trim();
        if (addition) value = [value.trim(), addition].filter(Boolean).join('\n');
    }

    async function handleAudioRecorded(event: CustomEvent<RecordedAudio>): Promise<void> {
        recording = false;
        const { realtime, liveTranscript } = event.detail;
        if (!realtime) {
            appendTranscript(liveTranscript ?? '');
            return;
        }
        transcribing = true;
        try {
            try {
                appendTranscript((await realtime.correction).transcript);
            } catch (correctionError) {
                // Correction is optional polish; fall back to the raw transcript.
                console.warn('[ReportIssueComposer] Transcript correction failed:', correctionError);
                appendTranscript((await realtime.transcription).transcript || liveTranscript || '');
            }
        } catch (transcriptionError) {
            console.error('[ReportIssueComposer] Dictation failed:', transcriptionError);
            notificationStore.error($text('settings.report_issue.dictation_failed'), 6000);
        } finally {
            transcribing = false;
            void refreshDictationQuota().catch((quotaError) => {
                console.warn('[ReportIssueComposer] Dictation quota request failed:', quotaError);
            });
        }
    }
</script>

<div class="report-issue-composer" data-testid="report-issue-composer">
    <SettingsSectionHeading title={$text('settings.report_issue.issue_text_label')} icon="chat" />
    <div class="report-issue-composer-input">
        <SettingsTextarea
            bind:value
            id="issue-title"
            dataTestid="report-issue-title"
            placeholder={$text('settings.report_issue.issue_text_placeholder')}
            disabled={disabled || transcribing}
            ariaLabel={$text('settings.report_issue.issue_text_label')}
            rows={6}
        />
        {#if recording}
            <RecordAudio
                initialPosition={{ x: 0, y: 0 }}
                enableRealtime={true}
                {anonymous}
                purpose={anonymous ? undefined : 'report_issue'}
                maxDurationSeconds={anonymous ? MAX_RECORDING_SECONDS : maxRecordingSeconds}
                on:audiorecorded={(event) => void handleAudioRecorded(event)}
                on:transcriptionerror={(event) => handleTranscriptionError(event.detail)}
                on:close={() => (recording = false)}
                on:cancel={() => (recording = false)}
            />
        {/if}
    </div>
    {#if error}
        <InputWarning message={error} />
    {/if}

    <div class="report-issue-actions" role="group" aria-label={$text('settings.report_issue.quick_actions_label')}>
        {#if canAttachImage}
            <button
                type="button"
                class="report-issue-action"
                data-testid="report-issue-attach-image"
                aria-label={$text('settings.report_issue.upload_screenshot')}
                {disabled}
                onclick={onAttachImage}
                use:tooltip
            >
                <span class="clickable-icon icon_image" aria-hidden="true"></span>
            </button>
        {/if}
        <button
            type="button"
            class="report-issue-action"
            class:active={elementPickerActive}
            data-testid="report-issue-pick-element"
            aria-label={elementPickerActive
                ? $text('settings.report_issue.element_picker_active')
                : $text('settings.report_issue.select_ui_element')}
            aria-pressed={elementPickerActive}
            disabled={disabled || elementPickerActive}
            onclick={onPickElement}
            use:tooltip
        >
            <span class="clickable-icon icon_select" aria-hidden="true"></span>
        </button>
        <!-- aria-disabled (not disabled) keeps the "try again tomorrow" tooltip hoverable. -->
        <button
            type="button"
            class="report-issue-action"
            class:unavailable={!dictationAvailable}
            data-testid="report-issue-dictate"
            aria-label={dictationAvailable
                ? $text('settings.report_issue.record_voice')
                : $text('settings.report_issue.dictation_unavailable_today')}
            aria-disabled={!dictationAvailable}
            aria-busy={transcribing}
            disabled={disabled || recording || transcribing}
            onclick={startDictation}
            use:tooltip
        >
            <span class="clickable-icon icon_recordaudio" aria-hidden="true"></span>
        </button>
    </div>
</div>

<style>
    .report-issue-composer {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-4);
    }

    .report-issue-actions {
        display: flex;
        gap: var(--spacing-4);
    }

    /* Compact rounded-rectangle icon buttons under the report text. */
    .report-issue-action {
        all: unset;
        box-sizing: border-box;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 44px;
        height: 36px;
        border-radius: var(--radius-3);
        background: var(--color-grey-20);
        cursor: pointer;
        transition: background-color var(--duration-fast, 150ms) ease-out;
    }

    .report-issue-action:hover:not(:disabled):not([aria-disabled='true']),
    .report-issue-action.active {
        background: var(--color-grey-30);
    }

    .report-issue-action:focus-visible {
        outline: 2px solid var(--color-primary-start);
        outline-offset: 2px;
    }

    .report-issue-action:disabled,
    .report-issue-action.unavailable {
        opacity: 0.4;
        cursor: not-allowed;
    }

    .report-issue-action .clickable-icon {
        display: block;
        width: 20px;
        height: 20px;
        background: var(--color-grey-60);
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        mask-size: contain;
    }

    /* RecordAudio is an absolutely positioned overlay over its nearest positioned parent. */
    .report-issue-composer-input {
        position: relative;
    }
</style>
