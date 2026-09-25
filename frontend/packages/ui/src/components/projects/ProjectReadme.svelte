<!-- Safe, GitHub-like renderer for a Project's root README.md. -->
<script lang="ts">
  import {
    releaseProjectReadmeImages,
    safeProjectReadmeImageUrl,
    type ProjectReadmeState,
  } from '../../services/projectReadme';

  interface Props {
    state: ProjectReadmeState;
    onUpload: () => void;
    onCreate: () => void;
    onRetry?: () => void;
  }

  let { state: readmeState, onUpload, onCreate, onRetry }: Props = $props();
  let rendered = $state('');
  let renderGeneration = 0;

  function trustedResolvedImageUrl(url: string | undefined): string | null {
    if (!url) return null;
    return /^(?:\/(?!\/)|blob:|data:image\/(?:png|jpeg|gif|webp|avif);base64,)/i.test(url) ? url : null;
  }

  async function renderMarkdown(markdown: string, imageUrls: Record<string, string>): Promise<void> {
    const generation = ++renderGeneration;
    try {
      const [{ default: MarkdownIt }, { default: DOMPurify }] = await Promise.all([
        import('markdown-it'),
        import('dompurify'),
      ]);
      const md = new MarkdownIt({ html: false, linkify: true, typographer: true, breaks: false });
      const document = new DOMParser().parseFromString(md.render(markdown), 'text/html');

      for (const image of document.querySelectorAll('img')) {
        const source = image.getAttribute('src') ?? '';
        const safeUrl = trustedResolvedImageUrl(imageUrls[source]) ?? safeProjectReadmeImageUrl(source);
        if (!safeUrl) {
          const placeholder = document.createElement('span');
          placeholder.className = 'readme-image-placeholder';
          placeholder.textContent = image.getAttribute('alt')
            ? `[Image: ${image.getAttribute('alt')}]`
            : '[Image unavailable]';
          image.replaceWith(placeholder);
          continue;
        }
        image.setAttribute('src', safeUrl);
        image.setAttribute('loading', 'lazy');
        image.setAttribute('decoding', 'async');
      }

      for (const link of document.querySelectorAll('a')) {
        const href = link.getAttribute('href') ?? '';
        if (/^https?:\/\//i.test(href) || /^mailto:/i.test(href)) {
          link.setAttribute('target', '_blank');
          link.setAttribute('rel', 'noopener noreferrer');
        } else if (!href.startsWith('#')) {
          link.removeAttribute('href');
        }
      }

      const clean = DOMPurify.sanitize(document.body.innerHTML, {
        ALLOWED_TAGS: [
          'p', 'br', 'hr', 'strong', 'b', 'em', 'i', 's', 'del',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
          'blockquote', 'code', 'pre', 'a', 'img', 'span',
          'table', 'thead', 'tbody', 'tr', 'th', 'td',
        ],
        ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'src', 'alt', 'loading', 'decoding', 'class'],
        ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|blob:|data:image\/(?:png|jpeg|gif|webp|avif);base64,|\/(?!\/)|#)/i,
      });
      if (generation === renderGeneration) rendered = clean;
    } catch {
      if (generation !== renderGeneration) return;
      rendered = markdown
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
    }
  }

  $effect(() => {
    if (readmeState.status === 'ready') {
      void renderMarkdown(readmeState.document.content, readmeState.document.imageUrls);
    } else {
      renderGeneration += 1;
      rendered = '';
    }
  });

  $effect(() => {
    if (readmeState.status !== 'ready') return;
    const document = readmeState.document;
    return () => releaseProjectReadmeImages(document);
  });
</script>

<section class="project-readme" data-testid="project-readme" aria-label="Project overview">
  {#if readmeState.status === 'loading'}
    <div class="status-message" data-testid="project-readme-loading" aria-live="polite">Loading project overview…</div>
  {:else if readmeState.status === 'ready'}
    <article class="readme-content" data-testid="project-readme-content">
      {#if readmeState.document.truncated}
        <p class="readme-notice">This overview is truncated at the safe read limit.</p>
      {/if}
      <!-- Content is rendered from Markdown with raw HTML disabled, then sanitized. -->
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      <div class="markdown-body">{@html rendered}</div>
    </article>
  {:else if readmeState.status === 'error'}
    <div class="empty-overview" data-testid="project-readme-error" role="alert">
      <p>{readmeState.message}</p>
      {#if onRetry}
        <button type="button" class="retry-button" data-testid="project-readme-retry" onclick={onRetry}>Retry</button>
      {/if}
    </div>
  {:else}
    <div class="empty-overview" data-testid="project-readme-empty">
      <p>No project overview created yet.</p>
      <div class="empty-actions">
        <button type="button" data-testid="project-readme-upload" onclick={onUpload}>
          <span class="readme-action-icon tray-icon upload-icon" aria-hidden="true"></span>
          <span>Upload</span>
        </button>
        <button type="button" data-testid="project-readme-create" onclick={onCreate}>
          <span class="clickable-icon icon_create readme-action-icon project-create-action-icon" aria-hidden="true"></span>
          <span>Create</span>
        </button>
      </div>
    </div>
  {/if}
</section>

<style>
  .project-readme {
    width: 100%;
    min-height: 18rem;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font-family: var(--font-primary, 'Lexend Deca Variable'), 'Lexend Deca', system-ui, sans-serif;
    overflow: hidden;
  }

  .status-message,
  .empty-overview {
    min-height: 18rem;
    display: grid;
    place-items: center;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    text-align: center;
  }

  .empty-overview {
    align-content: center;
    gap: var(--spacing-12);
    padding: var(--spacing-16) var(--spacing-8);
  }

  .empty-overview p {
    margin: 0;
  }

  .retry-button {
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-full);
    padding: var(--spacing-4) var(--spacing-12);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font: inherit;
    cursor: pointer;
  }

  .empty-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(7rem, 1fr));
    border-top: 1px solid var(--color-grey-25);
  }

  .empty-actions button {
    min-height: 7.5rem;
    display: grid;
    place-items: center;
    align-content: center;
    gap: var(--spacing-4);
    padding: var(--spacing-8) var(--spacing-12);
    border: 0;
    background: transparent;
    color: var(--color-font-secondary);
    font: inherit;
    border-radius: 0;
    box-shadow: none;
    filter: none;
    text-shadow: none;
    text-align: center;
    cursor: pointer;
  }

  .readme-action-icon {
    display: block;
    width: 1.75rem;
    height: 1.75rem;
    justify-self: center;
    margin-inline: auto;
    background: currentColor;
    box-shadow: none;
    filter: none;
    text-shadow: none;
  }

  .upload-icon {
    -webkit-mask: var(--icon-url-upload) center / contain no-repeat;
    mask: var(--icon-url-upload) center / contain no-repeat;
  }

  .empty-actions button + button {
    border-left: 1px solid var(--color-grey-25);
  }

  .empty-actions button:hover,
  .empty-actions button:focus-visible {
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    box-shadow: none;
  }

  .empty-actions button:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: -2px;
  }

  .readme-content {
    padding: var(--spacing-12);
  }

  .readme-notice {
    margin: 0 0 var(--spacing-8);
    padding: var(--spacing-6) var(--spacing-8);
    border-radius: var(--radius-3);
    background: var(--color-warning-bg);
    color: var(--color-warning);
    font-size: var(--font-size-small);
  }

  .markdown-body {
    max-width: 56rem;
    margin: 0 auto;
    overflow-wrap: anywhere;
    line-height: 1.65;
    user-select: text;
  }

  .markdown-body :global(h1),
  .markdown-body :global(h2),
  .markdown-body :global(h3),
  .markdown-body :global(h4) {
    margin: 1.5em 0 0.65em;
    line-height: 1.25;
  }

  .markdown-body :global(h1:first-child),
  .markdown-body :global(h2:first-child) {
    margin-top: 0;
  }

  .markdown-body :global(h1),
  .markdown-body :global(h2) {
    padding-bottom: var(--spacing-4);
    border-bottom: 1px solid var(--color-grey-25);
  }

  .markdown-body :global(h1) { font-size: var(--font-size-h2); }
  .markdown-body :global(h2) { font-size: var(--font-size-h3); }
  .markdown-body :global(h3) { font-size: var(--font-size-h4); }

  .markdown-body :global(p),
  .markdown-body :global(ul),
  .markdown-body :global(ol),
  .markdown-body :global(blockquote),
  .markdown-body :global(pre),
  .markdown-body :global(table) {
    margin: 0 0 var(--spacing-8);
  }

  .markdown-body :global(a) {
    color: var(--color-primary);
    text-decoration: underline;
    text-underline-offset: 0.15em;
  }

  .markdown-body :global(img) {
    display: block;
    max-width: 100%;
    height: auto;
    margin: var(--spacing-8) auto;
    border-radius: var(--radius-3);
  }

  .markdown-body :global(.readme-image-placeholder) {
    display: inline-block;
    padding: var(--spacing-4) var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .markdown-body :global(pre) {
    overflow-x: auto;
    padding: var(--spacing-8);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
  }

  .markdown-body :global(code) {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: var(--font-size-small);
  }

  .markdown-body :global(pre code) {
    padding: 0;
    background: transparent;
    color: inherit;
  }

  .markdown-body :global(:not(pre) > code) {
    padding: 0.15em 0.35em;
    border-radius: var(--radius-2);
    background: var(--color-grey-10);
  }

  .markdown-body :global(blockquote) {
    padding-left: var(--spacing-8);
    border-left: 4px solid var(--color-grey-30);
    color: var(--color-font-tertiary);
  }

  .markdown-body :global(table) {
    display: block;
    width: max-content;
    max-width: 100%;
    overflow-x: auto;
    border-collapse: collapse;
  }

  .markdown-body :global(th),
  .markdown-body :global(td) {
    padding: var(--spacing-4) var(--spacing-8);
    border: 1px solid var(--color-grey-30);
    text-align: left;
  }

  .markdown-body :global(th) {
    background: var(--color-grey-10);
  }

  @media (max-width: 480px) {
    .project-readme,
    .status-message,
    .empty-overview { min-height: 15rem; }
    .readme-content { padding: var(--spacing-8); }
    .empty-actions button { min-height: 6.5rem; }
  }
</style>
