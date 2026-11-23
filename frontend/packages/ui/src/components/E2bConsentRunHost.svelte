<!--
  frontend/packages/ui/src/components/E2bConsentRunHost.svelte

  Mount point of the run-start consent dialog; wires the gate's dialog store to
  E2bConsentRunDialog. Mounted by the views that start runs and previews.
-->
<script lang="ts">
  import E2bConsentRunDialog from './E2bConsentRunDialog.svelte';
  import { answerE2bConsentDialog, e2bConsentDialogOpen } from '../stores/e2bConsentDialogStore';
</script>

<E2bConsentRunDialog open={$e2bConsentDialogOpen} onAnswer={answerE2bConsentDialog}
  onDismiss={() => answerE2bConsentDialog('dismissed')} />
