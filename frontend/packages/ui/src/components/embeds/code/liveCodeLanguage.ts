/** Maps a file name or language label to a CodeMirror language extension (highlighting only). */
import type { Extension } from '@codemirror/state';
import { javascript } from '@codemirror/lang-javascript';
import { python } from '@codemirror/lang-python';
import { html } from '@codemirror/lang-html';
import { css } from '@codemirror/lang-css';
import { json } from '@codemirror/lang-json';
import { markdown } from '@codemirror/lang-markdown';

export function liveCodeLanguage(nameOrLanguage: string | undefined): Extension[] {
	const key = (nameOrLanguage ?? '').toLowerCase().split('.').pop() ?? '';
	switch (key) {
		case 'ts': case 'tsx': case 'typescript': return [javascript({ typescript: true, jsx: key === 'tsx' })];
		case 'js': case 'jsx': case 'mjs': case 'javascript': return [javascript({ jsx: key === 'jsx' })];
		case 'py': case 'python': return [python()];
		case 'html': case 'svelte': return [html()];
		case 'css': return [css()];
		case 'json': return [json()];
		case 'md': case 'markdown': return [markdown()];
		default: return [];
	}
}
