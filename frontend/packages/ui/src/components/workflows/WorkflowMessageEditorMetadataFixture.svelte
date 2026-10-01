<!-- Preview-only controlled fixture for schemas arriving after an editor mounts. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import WorkflowMessageEditor from './WorkflowMessageEditor.svelte';
  import type { Output } from './workflowBuilder';

  let value = $state('Summarize: {{steps.events.results}}');
  let outputs = $state<Output[]>([]);
  let changes = $state(0);

  onMount(() => {
    const loadOutputs = (event: Event) => {
      outputs = (event as CustomEvent<Output[]>).detail;
    };
    window.addEventListener('workflow-preview-output-metadata', loadOutputs);
    return () => window.removeEventListener('workflow-preview-output-metadata', loadOutputs);
  });
</script>

<div data-testid="workflow-editor-metadata-fixture" data-template={value} data-change-count={changes}>
  <WorkflowMessageEditor
    {value} {outputs} placeholder="Type @ to add a variable"
    onChange={(next) => { value = next; changes += 1; }}
    onMentionTrigger={() => {}}
  />
</div>
