import { createRawSnippet } from 'svelte';

export default {
  appId: 'home', skillId: 'listing', skillIconName: 'home',
  embedHeaderTitle: 'A shared result layout', result: {}, onClose: () => {},
  summary: createRawSnippet(() => ({ render: () => '<span>850 EUR · December 2026 · 29 m²</span>' })),
  detailContent: createRawSnippet(() => ({ render: () => '<p class="result-description">A compact result detail with the shared gradient header and follow-up composer.</p>' })),
};
