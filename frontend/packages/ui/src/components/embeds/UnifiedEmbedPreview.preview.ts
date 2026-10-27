import { createRawSnippet } from 'svelte';

// Deliberately no resultPreview/previewTools opt-in or known content skill ID.
export default {
  id: 'legacy-automatic-result-preview', appId: 'code', skillId: 'future_output_type',
  skillIconName: 'code', skillName: 'Automatic result.txt', status: 'finished' as const,
  showStatus: false, presentationOnly: true,
  onFullscreen: () => console.info('[Preview] automatic result expanded'),
  details: createRawSnippet(() => ({ render: () => '<p data-testid="automatic-result-body">A result inherits the shared content shell without a per-result flag.</p>' })),
};
