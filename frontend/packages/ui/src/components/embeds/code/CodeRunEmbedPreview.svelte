<!--
  frontend/packages/ui/src/components/embeds/code/CodeRunEmbedPreview.svelte

  Preview card for the Code app's "run" skill when it runs a cloud command in a
  Project sandbox. Shows the command line while it runs, then its exit code.
  The parent card content is written by backend/apps/code/tasks/command_parent_embed.py
  (command, argv, cwd, exit_code, embed_ids); the full output lives in the child
  terminal embed that fullscreen opens.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  interface Props {
    id: string;
    command?: string;
    argv?: string[];
    /** Project folder; already part of the shown command line, kept for callers. */
    cwd?: string;
    exitCode?: number | string;
    durationSeconds?: number;
    /** Last lines of the guarded output; the full output is in the terminal card. */
    outputTail?: string;
    error?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    command: commandProp,
    argv: argvProp,
    exitCode: exitCodeProp,
    durationSeconds: durationProp,
    outputTail: outputTailProp,
    error: errorProp,
    status: statusProp,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let command = $state('');
  let argv = $state<string[]>([]);
  let exitCode = $state<number | undefined>(undefined);
  let durationSeconds = $state<number | undefined>(undefined);
  let outputTail = $state('');
  let error = $state('');
  let status = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');

  function parseExitCode(raw: number | string | undefined): number | undefined {
    if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
    if (typeof raw === 'string' && raw.trim() !== '') {
      const parsed = Number.parseInt(raw, 10);
      if (Number.isFinite(parsed)) return parsed;
    }
    return undefined;
  }

  $effect(() => {
    if (commandProp !== undefined) command = commandProp || '';
    if (argvProp !== undefined) argv = argvProp || [];
    if (exitCodeProp !== undefined) exitCode = parseExitCode(exitCodeProp);
    if (durationProp !== undefined) durationSeconds = durationProp;
    if (outputTailProp !== undefined) outputTail = outputTailProp || '';
    if (errorProp !== undefined) error = errorProp || '';
    if (statusProp !== undefined) status = statusProp || 'processing';
  });

  let skillName = $derived($text('app_skills.code.run'));
  // Older cards carry only argv; the backend command line also names the folder.
  let commandLine = $derived(command || (argv.length ? `$ ${argv.join(' ')}` : ''));
  let durationText = $derived(durationSeconds === undefined ? ''
    : durationSeconds < 60 ? `${durationSeconds.toFixed(1)} s` : `${Math.floor(durationSeconds / 60)} min ${Math.round(durationSeconds % 60)} s`);
  let exitText = $derived([exitCode === undefined ? '' : `exit ${exitCode}`, durationText].filter(Boolean).join(' · '));
  let statusText = $derived.by(() => {
    if (status === 'error') return [$text('embeds.code.test_result.status_failed'), exitText].filter(Boolean).join(' · ');
    if (status === 'finished') return exitText;
    return '';
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      status = data.status;
    }
    const content = data.decodedContent;
    if (typeof content.command === 'string') command = content.command;
    if (Array.isArray(content.argv)) argv = content.argv.map(String);
    if (typeof content.exit_code === 'number' || typeof content.exit_code === 'string') exitCode = parseExitCode(content.exit_code);
    if (typeof content.duration_seconds === 'number') durationSeconds = content.duration_seconds;
    if (typeof content.output_tail === 'string') outputTail = content.output_tail;
    if (typeof content.error === 'string') error = content.error;
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="run"
  skillIconName="server"
  showSkillIcon={true}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="code-run-details" class:mobile={isMobileLayout} data-testid="code-run-details" data-run-status={status}>
      <pre class="code-run-command" data-testid="code-run-command">{commandLine}</pre>
      {#if status === 'error'}
        <div class="code-run-result failed" data-testid="code-run-result">{statusText}</div>
        {#if error && exitCode === undefined}
          <div class="code-run-error">{error}</div>
        {/if}
      {:else if status === 'finished'}
        <div class="code-run-result ok" data-testid="code-run-result">{exitText}</div>
      {/if}
      {#if outputTail && status !== 'processing'}
        <pre class="code-run-output" data-testid="code-run-output">{outputTail}</pre>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .code-run-details {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    justify-content: center;
    height: 100%;
    min-width: 0;
  }

  .code-run-output {
    margin: 0;
    font-family: var(--font-mono, monospace);
    font-size: var(--font-size-xxs, 0.75rem);
    color: var(--color-grey-60);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .code-run-command {
    margin: 0;
    font-family: var(--font-family-mono, monospace);
    font-size: var(--font-size-small);
    font-weight: 600;
    color: var(--color-font-primary);
    white-space: pre-wrap;
    word-break: break-all;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .code-run-result {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
  }

  .code-run-result.failed,
  .code-run-error {
    color: var(--color-error);
  }

  .code-run-error {
    font-size: var(--font-size-small);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
