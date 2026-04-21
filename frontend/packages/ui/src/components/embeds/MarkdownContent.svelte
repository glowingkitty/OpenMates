<!--
  frontend/packages/ui/src/components/embeds/MarkdownContent.svelte

  Shared component for rendering markdown text in embed fullscreens.
  Uses markdown-it (linkify + typographer) + DOMPurify for XSS safety.
  All links open in a new tab with noopener noreferrer.

  Usage:
    <MarkdownContent content={event.description} />

  See docs/architecture/messaging/embeds.md
-->

<script lang="ts">
  interface Props {
    /** Markdown or plain text to render */
    content: string;
    /** Additional CSS class for the container */
    class?: string;
  }

  let { content, class: extraClass = '' }: Props = $props();

  let rendered = $state('');

  async function renderMarkdown(text: string): Promise<void> {
    if (!text) { rendered = ''; return; }

    try {
      const [MarkdownItModule, DOMPurifyModule] = await Promise.all([
        import('markdown-it'),
        import('dompurify'),
      ]);
      const MarkdownIt = MarkdownItModule.default;
      const DOMPurify = DOMPurifyModule.default;

      const md = new MarkdownIt({
        html: false,   // never trust raw HTML from external sources
        linkify: true, // auto-linkify bare URLs
        typographer: true,
        breaks: true,  // treat single newlines as <br>
      });

      const rawHtml = md.render(text);

      DOMPurify.addHook('afterSanitizeAttributes', (node) => {
        if (node.tagName === 'A') {
          node.setAttribute('target', '_blank');
          node.setAttribute('rel', 'noopener noreferrer');
        }
      });

      rendered = DOMPurify.sanitize(rawHtml, {
        ALLOWED_TAGS: [
          'p', 'br', 'hr',
          'strong', 'b', 'em', 'i', 'u', 's', 'del',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'ul', 'ol', 'li',
          'blockquote', 'code', 'pre',
          'a',
        ],
        ALLOWED_ATTR: ['href', 'title', 'target', 'rel'],
        ALLOWED_URI_REGEXP: /^(?:(?:f|ht)tps?|mailto|tel|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i,
      });

      DOMPurify.removeHook('afterSanitizeAttributes');
    } catch {
      // Safe fallback: escape HTML and preserve line breaks
      rendered = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
    }
  }

  $effect(() => {
    renderMarkdown(content);
  });
</script>

<!-- eslint-disable-next-line svelte/no-at-html-tags -->
<div class="markdown-content {extraClass}">{@html rendered}</div>

<style>
  .markdown-content {
    font-size: 0.875rem;
    color: var(--color-font-primary);
    line-height: 1.65;
    word-break: break-word;
  }

  .markdown-content :global(p) {
    margin: 0 0 0.6em;
  }

  .markdown-content :global(p:last-child) {
    margin-bottom: 0;
  }

  .markdown-content :global(a) {
    color: var(--color-primary, #e63c2e);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .markdown-content :global(a:hover) {
    opacity: 0.8;
  }

  .markdown-content :global(ul),
  .markdown-content :global(ol) {
    margin: 0.4em 0;
    padding-left: 1.4em;
  }

  .markdown-content :global(li) {
    margin-bottom: 0.2em;
  }

  .markdown-content :global(code) {
    font-size: 0.8125em;
    background: var(--color-grey-15);
    border-radius: 3px;
    padding: 1px 4px;
  }

  .markdown-content :global(blockquote) {
    margin: 0.5em 0;
    padding-left: 0.8em;
    border-left: 3px solid var(--color-grey-30);
    color: var(--color-font-secondary);
  }

  .markdown-content :global(h1),
  .markdown-content :global(h2),
  .markdown-content :global(h3) {
    font-size: 0.9375rem;
    font-weight: 600;
    margin: 0.6em 0 0.3em;
  }
</style>
