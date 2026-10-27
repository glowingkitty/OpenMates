<!-- Owner-side local draft fixture uses the real PII store and direct export action. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import DocsEmbedPreview from './DocsEmbedPreview.svelte';
  import { setEmbedPIIState, resetEmbedPIIState } from '../../../stores/embedPIIStore';
  let expanded = $state(0);
  onMount(() => {
    setEmbedPIIState([{ original: 'alex@example.test', placeholder: '[EMAIL_1]', type: 'email' }], false);
    return resetEmbedPIIState;
  });
</script>
<div data-testid="docs-download-fixture" data-expanded={expanded}>
  <DocsEmbedPreview
    id="draft:docs-download"
    filename="masked-notes.docx"
    title="Contact notes"
    htmlContent={'<h1>Contact notes</h1><p>Email alex@example.test for access.</p><script>globalThis.unsafe_document_marker = true</script>'}
    status="finished"
    needsSignup={true}
    onFullscreen={() => { expanded += 1; }}
  />
</div>
