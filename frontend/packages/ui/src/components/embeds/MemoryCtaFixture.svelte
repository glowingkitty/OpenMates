<!--
  Isolated interaction evidence for the production memory header button.
  The fixture owns only a reversible saved flag; styling and icon rendering
  come from EmbedHeaderCtaButton itself. No account or memory API is used.
  Both states retain their accessible label while omitting visible copy.
-->
<script lang="ts">
  import EmbedHeaderCtaButton from './EmbedHeaderCtaButton.svelte';

  let saved = $state(false);
</script>

<div class="memory-cta-fixture" data-testid="memory-cta-fixture">
  <EmbedHeaderCtaButton
    label={saved ? 'Forget' : 'Add memory'}
    iconName="heart"
    iconOnly
    pressed={saved}
    onclick={() => { saved = !saved; }}
    testId="memory-cta-toggle"
  />
</div>

<style>
  .memory-cta-fixture {
    display: grid;
    place-items: center;
    width: 220px;
    height: 140px;
    background: var(--color-grey-25);
    border-radius: 30px;
  }
</style>
