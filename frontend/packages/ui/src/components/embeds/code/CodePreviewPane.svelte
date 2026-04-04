<!--
  frontend/packages/ui/src/components/embeds/code/CodePreviewPane.svelte

  Renders markdown or HTML content in a safe preview pane.
  - Markdown: parsed via markdown-it, sanitized with DOMPurify, rendered as HTML.
  - HTML: sanitized with DOMPurify, rendered in a sandboxed iframe (no script execution).

  Security: All content is sanitized through DOMPurify before rendering.
  HTML uses a sandboxed iframe to prevent any script execution even if
  a sanitizer bypass is discovered.
-->

<script lang="ts">
  import DOMPurify from 'dompurify';
  import MarkdownIt from 'markdown-it';

  /**
   * Supported preview content types.
   * 'markdown' renders via markdown-it → DOMPurify → innerHTML.
   * 'html' renders via DOMPurify → sandboxed iframe srcdoc.
   */
  type PreviewType = 'markdown' | 'html';

  interface Props {
    /** Raw code content to render as preview */
    code: string;
    /** Content type: 'markdown' or 'html' */
    previewType: PreviewType;
  }

  let { code, previewType }: Props = $props();

  /** Shared markdown-it instance — configured for safe defaults. */
  const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true
  });

  /**
   * DOMPurify config for markdown rendering (rendered inline, not in iframe).
   * Allows common HTML tags produced by markdown-it but strips scripts and events.
   */
  const MD_SANITIZE_OPTIONS: DOMPurify.Config = {
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'p', 'br', 'hr',
      'ul', 'ol', 'li',
      'blockquote', 'pre', 'code',
      'a', 'strong', 'em', 'del', 's', 'mark', 'sub', 'sup',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'img',
      'div', 'span',
      'details', 'summary',
      'dl', 'dt', 'dd'
    ],
    ALLOWED_ATTR: [
      'href', 'title', 'alt', 'src', 'width', 'height',
      'class', 'id',
      'target', 'rel',
      'colspan', 'rowspan', 'align'
    ],
    ALLOW_DATA_ATTR: false
  };

  /**
   * DOMPurify config for HTML rendering (rendered in sandboxed iframe).
   * Preserves full document structure including <style> tags and inline styles.
   * Safe because the iframe uses sandbox="" which blocks all script execution.
   */
  const HTML_SANITIZE_OPTIONS: DOMPurify.Config = {
    WHOLE_DOCUMENT: true,
    ADD_TAGS: ['style', 'link', 'meta'],
    ADD_ATTR: ['style'],
    ALLOW_DATA_ATTR: false
  };

  /**
   * Rendered HTML for markdown content (inline rendering).
   */
  let renderedMarkdownHtml = $derived.by(() => {
    if (previewType !== 'markdown') return '';
    const rawHtml = md.render(code);
    return DOMPurify.sanitize(rawHtml, MD_SANITIZE_OPTIONS);
  });

  /**
   * Sanitized HTML document for the sandboxed iframe.
   * WHOLE_DOCUMENT: true preserves the original <html>/<head>/<style> structure.
   * If the source HTML has no <style> tag, a basic fallback stylesheet is injected.
   */
  let iframeSrcdoc = $derived.by(() => {
    if (previewType !== 'html') return '';
    const sanitized = DOMPurify.sanitize(code, HTML_SANITIZE_OPTIONS);
    // If the source HTML already has its own styles, use it as-is
    if (sanitized.includes('<style')) return sanitized;
    // Otherwise inject a basic fallback stylesheet for readability
    const fallbackStyle = `<style>
  body { margin: 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; }
  img { max-width: 100%; height: auto; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
  pre { background: #f5f5f5; padding: 12px; border-radius: 6px; overflow-x: auto; }
  code { font-family: 'SF Mono', Monaco, Consolas, monospace; font-size: 0.9em; }
  blockquote { border-left: 3px solid #ddd; margin-left: 0; padding-left: 16px; color: #666; }
</style>`;
    // Inject before </head> if present, otherwise prepend
    if (sanitized.includes('</head>')) {
      return sanitized.replace('</head>', fallbackStyle + '</head>');
    }
    return fallbackStyle + sanitized;
  });
</script>

<div class="code-preview-pane">
  {#if previewType === 'markdown'}
    <!-- Markdown: rendered inline with sanitized HTML -->
    <div class="markdown-preview">
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      {@html renderedMarkdownHtml}
    </div>
  {:else}
    <!-- HTML: rendered in sandboxed iframe — no script execution allowed -->
    <iframe
      class="html-preview-iframe"
      sandbox=""
      srcdoc={iframeSrcdoc}
      title="HTML Preview"
    ></iframe>
  {/if}
</div>

<style>
  .code-preview-pane {
    /* Absolutely fill the parent .preview-panel so the iframe doesn't
       expand the container to its content height. Scrolling happens
       inside the iframe (for HTML) or inside this div (for markdown). */
    position: absolute;
    inset: 0;
    overflow: auto;
    background-color: var(--color-grey-15);
  }

  /* ── Markdown preview ── */
  .markdown-preview {
    padding: 24px;
    color: var(--color-font-primary);
    line-height: 1.7;
    font-size: 0.95rem;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }

  /* Headings */
  .markdown-preview :global(h1) {
    font-size: 1.8rem;
    font-weight: 700;
    margin: 1.5rem 0 0.75rem;
    padding-bottom: 0.3rem;
    border-bottom: 1px solid var(--color-grey-20);
  }

  .markdown-preview :global(h2) {
    font-size: 1.4rem;
    font-weight: 600;
    margin: 1.25rem 0 0.6rem;
    padding-bottom: 0.2rem;
    border-bottom: 1px solid var(--color-grey-20);
  }

  .markdown-preview :global(h3) {
    font-size: 1.15rem;
    font-weight: 600;
    margin: 1rem 0 0.5rem;
  }

  .markdown-preview :global(h4),
  .markdown-preview :global(h5),
  .markdown-preview :global(h6) {
    font-size: 1rem;
    font-weight: 600;
    margin: 0.8rem 0 0.4rem;
  }

  /* Paragraphs and inline */
  .markdown-preview :global(p) {
    margin: 0.6rem 0;
  }

  .markdown-preview :global(a) {
    color: var(--color-primary);
    text-decoration: none;
  }

  .markdown-preview :global(a:hover) {
    text-decoration: underline;
  }

  .markdown-preview :global(strong) {
    font-weight: 600;
  }

  .markdown-preview :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    margin: 0.5rem 0;
  }

  /* Lists */
  .markdown-preview :global(ul),
  .markdown-preview :global(ol) {
    padding-left: 1.5rem;
    margin: 0.5rem 0;
  }

  .markdown-preview :global(li) {
    margin: 0.2rem 0;
  }

  /* Code */
  .markdown-preview :global(code) {
    font-family: 'SF Mono', Monaco, Consolas, monospace;
    font-size: 0.88em;
    background: var(--color-grey-20);
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
  }

  .markdown-preview :global(pre) {
    background: var(--color-grey-20);
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 0.6rem 0;
  }

  .markdown-preview :global(pre code) {
    background: none;
    padding: 0;
  }

  /* Blockquote */
  .markdown-preview :global(blockquote) {
    border-left: 3px solid var(--color-grey-25);
    margin: 0.6rem 0;
    padding: 0.2rem 0 0.2rem 16px;
    color: var(--color-font-secondary);
  }

  /* Table */
  .markdown-preview :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 0.6rem 0;
  }

  .markdown-preview :global(th),
  .markdown-preview :global(td) {
    border: 1px solid var(--color-grey-20);
    padding: 8px 12px;
    text-align: left;
  }

  .markdown-preview :global(th) {
    background: var(--color-grey-20);
    font-weight: 600;
  }

  /* Horizontal rule */
  .markdown-preview :global(hr) {
    border: none;
    border-top: 1px solid var(--color-grey-20);
    margin: 1rem 0;
  }

  /* ── HTML iframe preview ── */
  .html-preview-iframe {
    width: 100%;
    height: 100%;
    border: none;
    background: var(--color-grey-15);
  }
</style>
