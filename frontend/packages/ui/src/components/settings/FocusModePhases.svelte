<!-- Web counterpart: apple/OpenMates/Sources/Features/Settings/Views/SettingsAppsFull.swift focusDetail -->
<script lang="ts">
  import type { FocusPhaseDefinition } from '../../types/apps';
  import { text } from '../../i18n/translations';
  let { phases }: { phases: FocusPhaseDefinition[] } = $props();
  // Authored instructions are hard-wrapped YAML blocks: a single line break is
  // source wrapping, a blank line starts a new paragraph.
  const paragraphs = (instructions: string): string[] =>
    instructions.split(/\n\s*\n/).map(part => part.replace(/\s*\n\s*/g, ' ').trim()).filter(Boolean);
</script>
<section data-testid="focus-mode-phases" aria-label={$text('focus_phases.phases')}>
  <h2>{$text('focus_phases.phases')}</h2>
  {#each phases as phase, index (phase.id)}
    <section id={`focus-phase-${phase.id}`} class="phase" data-testid="focus-mode-phase">
      <h3>{index + 1}. {phase.title}</h3>
      <div class="instructions" data-testid="focus-phase-instructions">
        {#each paragraphs(phase.instructions) as paragraph, paragraphIndex (paragraphIndex)}<p>{paragraph}</p>{/each}
      </div>
      <h4>{$text('focus_phases.requirements')}</h4>
      <ul>{#each phase.requirements as requirement (requirement.id)}
        <li data-testid="focus-phase-requirement">{requirement.text}
          {#if requirement.type === 'user_confirmation'}<span class="confirmation">{$text('focus_phases.confirmation')}</span>{/if}
        </li>
      {/each}</ul>
    </section>
  {/each}
</section>
<style>
  h2, h3, h4 { color: var(--color-grey-100); font-weight: 500; }
  h2 { font-size: var(--font-size-h3); } h3 { font-size: var(--font-size-h4); } h4 { font-size: var(--font-size-p); margin-bottom: 8px; }
  .phase { margin-block: 24px; } .instructions { color: var(--color-grey-70); line-height: 1.6; } .instructions p { margin-block: 0 12px; line-height: 1.6; }
  ul { padding-inline-start: 22px; color: var(--color-grey-70); line-height: 1.6; }
  li { margin-block: 8px; } .confirmation { display: block; font-size: var(--font-size-small); color: var(--color-grey-70); }
</style>
