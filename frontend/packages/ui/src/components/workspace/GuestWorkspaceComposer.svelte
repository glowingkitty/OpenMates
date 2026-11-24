<script lang="ts">
  import { text } from '../../i18n/translations';
  import { openGuestAccountEntry } from '../../utils/guestAccountEntry';
  import WorkspaceHomeShell from './WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from './WorkspacePromptComposer.svelte';

  let { surface, heading, prompt }: { surface: 'projects' | 'tasks'; heading: string; prompt: string } = $props();
</script>

<div class="guest-workspace">
  <WorkspaceHomeShell {surface} {heading} showReportIssue testId={`${surface}-guest-composer`}>
    <svelte:fragment slot="composer">
      <WorkspacePromptComposer
        {surface}
        placeholder={prompt}
        submitLabel={$text('enter_message.send')}
        submittingLabel={$text('enter_message.send')}
        disabled={false}
        submitting={false}
        inputTestId={`${surface}-guest-account`}
        onSubmit={openGuestAccountEntry}
        onMicClick={openGuestAccountEntry}
        onAccountRequired={openGuestAccountEntry}
        fileImport={{ label: $text('enter_message.attachments.attach_files'), testId: `${surface}-guest-files`, onClick: openGuestAccountEntry }}
      />
    </svelte:fragment>
  </WorkspaceHomeShell>
</div>

<style>
  .guest-workspace {
    flex: 1;
    min-width: 0;
    min-height: 0;
  }
</style>
