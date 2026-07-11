<!--
  Canonical Workflow detail route.
  Reuses the authenticated Workflows workspace while exposing a stable URL.
  The parent component reads workflow_id from page.params and opens the focused
  detail canvas without duplicating workflow state or persistence logic.
  Spec: docs/specs/workflows-v1/spec.yml
-->

<script lang="ts">
  import WorkflowsPage from '../+page.svelte';
</script>

<WorkflowsPage />
