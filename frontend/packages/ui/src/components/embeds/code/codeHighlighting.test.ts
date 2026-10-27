import { describe, expect, it } from 'vitest';
import { highlightCode, isLanguageSupported } from './codeHighlighting';

describe('Svelte code highlighting', () => {
  // contract-test: tooling
  // Regression for bundlers resolving the package's script-only browser entry.
  it('registers the module grammar and highlights template syntax without a global hljs', () => {
    expect(isLanguageSupported('svelte')).toBe(true);
    const output = highlightCode('{#if visible}<p>Hello {name}</p>{/if}', 'svelte');
    const container = document.createElement('div');
    container.innerHTML = output;

    expect(container.textContent).toBe('{#if visible}<p>Hello {name}</p>{/if}');
    expect(container.querySelector('.hljs-keyword')).not.toBeNull();
    expect(container.querySelector('p')).toBeNull();
  });
});
