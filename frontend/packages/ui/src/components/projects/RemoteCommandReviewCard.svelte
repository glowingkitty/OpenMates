<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { RemoteCommandEntry } from '../../stores/remoteCommandApprovalStore';

  interface Props {
    entry: RemoteCommandEntry;
    onDecision: (id: string, accepted: boolean) => void;
    onStop: (id: string) => void | Promise<void>;
  }
  let { entry, onDecision, onStop }: Props = $props();
  const stoppable = new Set(['preparing', 'waiting_for_executor', 'authorizing', 'running']);
</script>

<section class="command-card" data-testid="remote-command-review-card" data-status={entry.status}>
  <strong>{$text('projects.remote_command_title')}</strong>
  <p data-testid="remote-command-target">{entry.projectName} · {entry.sourceName}</p>
  <p class="status" role="status">{$text(`projects.remote_command_status_${entry.status}`)}</p>
  <p>{entry.review.explanation.summary}</p>
  {#each [entry.review.explanation.effects, entry.review.explanation.risks, entry.review.explanation.uncertainty] as points, index}
    {#if points.length}
      <p class="label">{$text(['projects.remote_command_effects', 'projects.remote_command_risks', 'projects.remote_command_uncertainty'][index])}</p>
      <ul>{#each points as point}<li>{point}</li>{/each}</ul>
    {/if}
  {/each}
  <p class="label">{$text('projects.remote_command_exact_arguments')}</p>
  <pre data-testid="remote-command-argv">{JSON.stringify(entry.review.command.argv, null, 2)}</pre>
  <dl>
    <dt>{$text('projects.remote_command_directory')}</dt><dd><code>{entry.review.command.cwd}</code></dd>
    <dt>{$text('projects.remote_command_source_access')}</dt><dd>{$text(`projects.remote_command_access_${entry.review.command.source_access}`)}</dd>
    <dt>{$text('projects.remote_command_mode')}</dt><dd>{$text(`projects.remote_command_mode_${entry.review.command.mode}`)}</dd>
    <dt>{$text('projects.remote_command_network')}</dt><dd>{entry.review.command.network_profile ?? $text('projects.remote_command_none')}</dd>
    <dt>{$text('projects.remote_command_writable')}</dt><dd>{entry.review.command.writable_profiles.join(', ') || $text('projects.remote_command_none')}</dd>
    <dt>{$text('projects.remote_command_credentials')}</dt><dd>{entry.review.command.credential_profiles.join(', ') || $text('projects.remote_command_none')}</dd>
    <dt>{$text('projects.remote_command_time_limit')}</dt><dd>{entry.review.command.deadline_ms / 1000} s</dd>
  </dl>
  {#if entry.latestOutput}
    <details open><summary>{$text('projects.remote_command_output')}</summary>
      <pre class="output" data-testid="remote-command-output">{entry.latestOutput}</pre>
    </details>
  {/if}
  {#if entry.errorCode}<p class="error" data-testid="remote-command-error">{$text('projects.remote_command_failed')}: <code>{entry.errorCode}</code></p>{/if}
  <div class="actions">
    {#if entry.status === 'pending'}
      <button class="approve" data-testid="remote-command-approve" onclick={() => onDecision(entry.id, true)}>{$text('projects.remote_command_approve')}</button>
      <button data-testid="remote-command-reject" onclick={() => onDecision(entry.id, false)}>{$text('projects.file_approval_reject')}</button>
    {:else if stoppable.has(entry.status)}
      <button data-testid="remote-command-stop" onclick={() => onStop(entry.id)}>{$text('projects.remote_command_stop')}</button>
    {/if}
  </div>
</section>

<style>
  .command-card { width: 100%; min-width: 0; box-sizing: border-box; padding: var(--spacing-6); border: 1px solid var(--color-grey-25); border-radius: var(--radius-7); background: var(--color-grey-10); color: var(--color-font-primary); overflow-wrap: anywhere; }
  strong { display: block; font-size: var(--font-size-p); }
  code { background: transparent; color: var(--color-font-primary); padding: 0; }
  p, li, dt, dd, summary { font-size: var(--font-size-small); }
  .status, dt { color: var(--color-font-secondary); }
  .label { font-weight: 600; margin-bottom: var(--spacing-2); }
  ul { padding-left: var(--spacing-6); margin-top: 0; }
  pre { overflow: auto; padding: var(--spacing-4); background: var(--color-grey-0); border-radius: var(--radius-4); font-size: var(--font-size-small); white-space: pre-wrap; overflow-wrap: anywhere; }
  .output { max-height: 20rem; white-space: pre; }
  dl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--spacing-2) var(--spacing-4); }
  dd { margin: 0; }
  summary { cursor: pointer; }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-3); margin-top: var(--spacing-5); }
  button { min-height: 2.75rem; border: 1px solid var(--color-grey-30); border-radius: var(--radius-4); padding: var(--spacing-3) var(--spacing-5); background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; }
  button.approve { background: var(--color-button-primary); color: var(--color-font-button); border-color: var(--color-button-primary); }
  button.approve:hover { background: var(--color-button-primary-hover); }
  button:focus-visible, summary:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  button.approve:focus-visible { outline-color: var(--color-primary); }
</style>
