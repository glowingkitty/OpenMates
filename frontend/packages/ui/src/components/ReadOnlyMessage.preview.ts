/** Focused parsed-message states for the read-only renderer. */
import { encode } from '@toon-format/toon';
import { embedStore } from '../services/embedStore';
import { chatSyncService } from '../services/chatSyncService';
const defaultProps = {
  role: 'user' as const,
  content: 'A saved message.',
  chatId: '',
};

const markdownLookingFirstText = 'Synthetic storage reference. STORAGE_CAPACITY_SCENARIO:round';
const codeEmbed = {
  type: 'embed',
  attrs: {
    id: 'd1acb994-29fd-48d8-9920-c6a8e990d6d3',
    type: 'code-code',
    status: 'finished',
    // GroupRenderer resolves inline code only for preview references. This
    // static form avoids the editor's auto-upgrade path used by preview:code:.
    contentRef: 'preview:read-only-code',
    language: 'js',
    code: 'const saved = 1;',
    filename: 'saved.js',
  },
};

const skillExecution = (id: string, status: 'error' | 'finished') => {
  // Static records model decrypted persisted output, including a stale finished
  // transport status. The TOON execution status must win after initial load/reload.
  embedStore.registerStaticEmbed({
    embedId: id, type: 'app-skill-use', appId: 'fitness', skillId: 'search_classes',
    content: encode({ app_id: 'fitness', skill_id: 'search_classes', status,
      error: status === 'error' ? 'The request timed out. Please try again.' : null,
      query: id === 'failed-fitness' ? 'Evening classes' : 'Morning classes',
      provider: 'Urban Sports Club', result_count: 0, embed_ids: [],
    }),
  });
  return { type: 'embed', attrs: {
    id, type: 'app-skill-use', status: 'finished', contentRef: `embed:${id}`,
    app_id: 'fitness', skill_id: 'search_classes',
  } };
};
const failedFitness = skillExecution('failed-fitness', 'error');
const successfulFitness = skillExecution('successful-fitness', 'finished');

const svgSource = '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="120" viewBox="0 0 240 120"><rect width="240" height="120" fill="steelblue"/><text x="20" y="65" fill="white">SVG image</text></svg>';
function seedSvgCode(code: string) {
  embedStore.registerStaticEmbed({ embedId: 'saved-svg-code', type: 'code-code',
    content: encode({ code, language: 'xml', filename: 'drawing.svg' }),
  });
  if (typeof document !== 'undefined') chatSyncService.dispatchEvent(new CustomEvent('embedUpdated', {
    detail: { embed_id: 'saved-svg-code', status: 'finished' },
  }));
}
seedSvgCode(svgSource);
if (typeof document !== 'undefined') {
  document.addEventListener('preview:update-svg-code', () => seedSvgCode(svgSource.replace(/240/g, '320')));
  document.addEventListener('preview:svg-to-html', () => seedSvgCode(`<html><body>${svgSource}</body></html>`));
}

export default defaultProps;

export const variants = {
  svgFenced: {
    ...defaultProps,
    role: 'assistant' as const,
    content: `Here is the modified SVG.\n\n\`\`\`xml:drawing.svg\n${svgSource.replace(' xmlns="http://www.w3.org/2000/svg"', '')}\n\`\`\`\n\nThe source is preserved.`,
  },
  svgSavedCode: {
    ...defaultProps,
    role: 'assistant' as const,
    content: '```json\n{"type":"code","embed_id":"saved-svg-code"}\n```',
  },
  svgUnlabelled: {
    ...defaultProps,
    role: 'assistant' as const,
    content: `\`\`\`\n${svgSource}\n\`\`\``,
  },
  failedSkillExecution: {
    ...defaultProps,
    role: 'assistant' as const,
    content: { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'The class search could not complete.' }] },
      { type: 'paragraph', content: [failedFitness] },
    ] },
  },
  groupedFailedSkillExecution: {
    ...defaultProps,
    role: 'assistant' as const,
    content: { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'One search failed; the other completed.' }] },
      { type: 'paragraph', content: [{ type: 'embed', attrs: {
        id: 'fitness-execution-group', type: 'app-skill-use-group', status: 'finished', contentRef: '',
        groupedItems: [failedFitness.attrs, successfulFitness.attrs], groupCount: 2,
      } }] },
    ] },
  },
  multilineUser: {
    ...defaultProps,
    content: 'Find **social posts** about rainy-day cafes.\nKeep the source link on its own line.\n\n\nInclude a short summary after the gap.',
  },
  multilineUserCode: {
    ...defaultProps,
    content: 'Before **saved code**.\n\n````svelte\nlet count = $state(0);\n\n```text\nnested\n\ncode\n```\n````\n\nAfter the code.',
  },
  multilineUserStructured: {
    ...defaultProps,
    content: '1. **First**\n\n   Still first with *emphasis*.\n\n1. Second\n\n- **Bullet first**\n\n- Bullet second\n\n> **Quote first**\n>\n> Quote second.',
  },
  parsedCode: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: markdownLookingFirstText }] },
        { type: 'paragraph', content: [codeEmbed] },
      ],
    },
  },
  parsedParagraphs: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: markdownLookingFirstText }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'Later saved paragraph.' }] },
      ],
    },
  },
  parsedInline: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [{
        type: 'paragraph',
        content: [
          { type: 'text', text: markdownLookingFirstText },
          { type: 'text', text: ' with inline saved content.' },
        ],
      }],
    },
  },
  parsedMarkedSingle: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [{
        type: 'paragraph',
        content: [{
          type: 'text',
          text: markdownLookingFirstText,
          marks: [{ type: 'bold' }],
        }],
      }],
    },
  },
  legacySingleMarkdown: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [{
        type: 'paragraph',
        content: [{ type: 'text', text: '**Legacy saved markdown**' }],
      }],
    },
  },
};
