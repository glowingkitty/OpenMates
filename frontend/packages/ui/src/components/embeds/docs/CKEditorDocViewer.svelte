<!--
  frontend/packages/ui/src/components/embeds/docs/CKEditorDocViewer.svelte
  
  CKEditor 5 document viewer component for rendering document HTML content.
  Uses DecoupledEditor in read-only mode for accurate document rendering.
  
  Features:
  - Renders HTML content through CKEditor's data model for accurate formatting
  - Read-only mode with no toolbar (viewing mode)
  - Dynamically loads CKEditor to keep initial bundle small
  - Provides getData() method for copy/download operations
  - Proper cleanup on destroy
  
  CKEditor is loaded lazily on first mount to avoid blocking initial page load.
  The editor instance is created with DecoupledEditor for a clean, toolbar-free
  document viewing experience. The toolbar is not appended to the DOM.
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  /**
   * Props for CKEditorDocViewer
   */
  interface Props {
    /** HTML content to render in the editor */
    htmlContent: string;
    /** Optional callback when editor is ready */
    onReady?: (editor: CKEditorInstance) => void;
  }

  /** Minimal type for the CKEditor instance we expose */
  interface CKEditorInstance {
    getData: () => string;
    setData: (data: string) => void;
    enableReadOnlyMode: (lockId: string) => void;
    disableReadOnlyMode: (lockId: string) => void;
  }

  let { htmlContent, onReady }: Props = $props();

  /** Reference to the editor container div */
  let editorContainer: HTMLDivElement | undefined = $state(undefined);

  /** CKEditor instance - stored for cleanup and data access */
  let editorInstance: CKEditorInstance | null = $state(null);

  /** Loading state while CKEditor initializes */
  let isLoading = $state(true);

  /** Error state if CKEditor fails to load */
  let loadError: string | null = $state(null);

  /** Lock ID for read-only mode */
  const READ_ONLY_LOCK_ID = 'doc-viewer-readonly';

  /**
   * Initialize CKEditor with DecoupledEditor in read-only mode.
   * Dynamically imports CKEditor to keep it out of the main bundle.
   */
  async function initEditor() {
    if (!editorContainer) return;

    try {
      // Dynamic import for code splitting - CKEditor is ~2MB
      const {
        DecoupledEditor,
        Essentials,
        Bold,
        Italic,
        Underline,
        Strikethrough,
        Subscript,
        Superscript,
        Paragraph,
        Heading,
        Font,
        FontFamily,
        FontSize,
        FontColor,
        FontBackgroundColor,
        Alignment,
        List,
        ListProperties,
        TodoList,
        Indent,
        IndentBlock,
        Table,
        TableToolbar,
        TableProperties,
        TableCellProperties,
        TableCaption,
        BlockQuote,
        Link,
        AutoLink,
        Image,
        ImageCaption,
        ImageStyle,
        ImageResize,
        CodeBlock,
        Code,
        HorizontalLine,
        MediaEmbed,
        RemoveFormat,
        FindAndReplace,
        HtmlEmbed,
        GeneralHtmlSupport,
        Style,
        ShowBlocks,
        SourceEditing,
        PageBreak,
      } = await import('ckeditor5');

      // Import CKEditor content styles for proper rendering
      await import('ckeditor5/ckeditor5.css');

      if (!editorContainer) return; // Component may have been destroyed during import

      const editor = await DecoupledEditor.create(editorContainer, {
        // GPL license for open-source usage
        licenseKey: 'GPL',

        // Plugins for comprehensive document rendering
        plugins: [
          Essentials,
          Bold,
          Italic,
          Underline,
          Strikethrough,
          Subscript,
          Superscript,
          Paragraph,
          Heading,
          Font,
          FontFamily,
          FontSize,
          FontColor,
          FontBackgroundColor,
          Alignment,
          List,
          ListProperties,
          TodoList,
          Indent,
          IndentBlock,
          Table,
          TableToolbar,
          TableProperties,
          TableCellProperties,
          TableCaption,
          BlockQuote,
          Link,
          AutoLink,
          Image,
          ImageCaption,
          ImageStyle,
          ImageResize,
          CodeBlock,
          Code,
          HorizontalLine,
          MediaEmbed,
          RemoveFormat,
          FindAndReplace,
          HtmlEmbed,
          GeneralHtmlSupport,
          Style,
          ShowBlocks,
          SourceEditing,
          PageBreak,
        ],

        // Empty toolbar - we don't show it in read-only mode
        // Will be populated when editing is enabled in the future
        toolbar: [],

        // Heading levels matching typical document structure
        heading: {
          options: [
            { model: 'paragraph' as const, title: 'Paragraph', class: 'ck-heading_paragraph' },
            { model: 'heading1' as const, view: 'h1', title: 'Heading 1', class: 'ck-heading_heading1' },
            { model: 'heading2' as const, view: 'h2', title: 'Heading 2', class: 'ck-heading_heading2' },
            { model: 'heading3' as const, view: 'h3', title: 'Heading 3', class: 'ck-heading_heading3' },
            { model: 'heading4' as const, view: 'h4', title: 'Heading 4', class: 'ck-heading_heading4' },
            { model: 'heading5' as const, view: 'h5', title: 'Heading 5', class: 'ck-heading_heading5' },
            { model: 'heading6' as const, view: 'h6', title: 'Heading 6', class: 'ck-heading_heading6' },
          ],
        },

        // Table configuration
        table: {
          contentToolbar: [
            'tableColumn',
            'tableRow',
            'mergeTableCells',
            'tableProperties',
            'tableCellProperties',
          ],
        },

        // Allow all HTML elements through GeneralHtmlSupport
        // This ensures the AI-generated HTML doesn't get stripped
        htmlSupport: {
          allow: [
            {
              name: /.*/,
              attributes: true,
              classes: true,
              styles: true,
            },
          ],
          disallow: [
            // Block dangerous elements
            { name: 'script' },
            { name: 'style' },
            { name: 'iframe' },
            { name: 'object' },
            { name: 'embed' },
            { name: 'form' },
            { name: 'input' },
            { name: 'button' },
            { name: 'select' },
            { name: 'textarea' },
          ],
        },

        // Link configuration
        link: {
          addTargetToExternalLinks: true,
          defaultProtocol: 'https://',
        },

        // Image configuration
        image: {
          resizeUnit: '%' as const,
          resizeOptions: [
            { name: 'resizeImage:original', value: null, label: 'Original' },
            { name: 'resizeImage:25', value: '25', label: '25%' },
            { name: 'resizeImage:50', value: '50', label: '50%' },
            { name: 'resizeImage:75', value: '75', label: '75%' },
          ],
        },

        // Initial data - set the HTML content
        initialData: htmlContent,
      });

      // Enable read-only mode - no editing, just viewing
      editor.enableReadOnlyMode(READ_ONLY_LOCK_ID);

      // Store the editor instance
      editorInstance = editor as unknown as CKEditorInstance;
      isLoading = false;

      console.debug('[CKEditorDocViewer] Editor initialized successfully');

      // Notify parent that editor is ready
      if (onReady) {
        onReady(editorInstance);
      }
    } catch (error) {
      console.error('[CKEditorDocViewer] Failed to initialize CKEditor:', error);
      loadError = error instanceof Error ? error.message : 'Failed to load document editor';
      isLoading = false;
    }
  }

  // Update editor content when htmlContent prop changes
  $effect(() => {
    if (editorInstance && htmlContent) {
      // Only update if content actually changed
      const currentData = editorInstance.getData();
      if (currentData !== htmlContent) {
        editorInstance.setData(htmlContent);
        console.debug('[CKEditorDocViewer] Content updated');
      }
    }
  });

  onMount(() => {
    initEditor();
  });

  onDestroy(() => {
    if (editorInstance) {
      // CKEditor's destroy() returns a promise but we don't need to await it in onDestroy
      const editor = editorInstance as unknown as { destroy: () => Promise<void> };
      editor.destroy().catch((err: Error) => {
        console.error('[CKEditorDocViewer] Error destroying editor:', err);
      });
      editorInstance = null;
    }
  });
</script>

<div class="ckeditor-doc-viewer">
  {#if isLoading}
    <div class="loading-placeholder">
      <div class="loading-shimmer"></div>
      <div class="loading-shimmer short"></div>
      <div class="loading-shimmer"></div>
      <div class="loading-shimmer medium"></div>
    </div>
  {/if}
  
  {#if loadError}
    <div class="load-error">
      <p>Failed to load document viewer</p>
      <p class="error-detail">{loadError}</p>
    </div>
  {/if}

  <!-- CKEditor mounts into this div -->
  <!-- The div must exist before editor init, hidden while loading -->
  <div
    class="editor-container"
    class:hidden={isLoading || !!loadError}
    bind:this={editorContainer}
  ></div>
</div>

<style>
  .ckeditor-doc-viewer {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
  }

  .editor-container {
    width: 100%;
    flex: 1;
  }

  .editor-container.hidden {
    position: absolute;
    visibility: hidden;
    pointer-events: none;
  }

  /* ===========================================
     CKEditor Content Area Styling Overrides
     Make the editor look like a clean document
     =========================================== */

  /* Remove CKEditor's default border and focus outline on the editable area */
  .editor-container :global(.ck.ck-editor__editable) {
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
    padding: 0 !important;
    background: transparent !important;
    min-height: auto !important;
    color: #1a1a1a;
    font-size: 15px;
    line-height: 1.75;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  }

  /* Ensure read-only mode doesn't show cursor or selection highlight */
  .editor-container :global(.ck.ck-editor__editable.ck-read-only) {
    cursor: default;
  }

  /* Remove any CKEditor chrome/wrapper styling */
  .editor-container :global(.ck.ck-editor__top) {
    display: none !important;
  }

  /* ===========================================
     Document Typography Overrides
     Match the document aesthetic from the design
     =========================================== */

  .editor-container :global(.ck-content h1) {
    font-size: 26px;
    font-weight: 700;
    margin: 0 0 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e0e0e0;
    color: #0d0d0d;
    line-height: 1.3;
  }

  .editor-container :global(.ck-content h2) {
    font-size: 21px;
    font-weight: 600;
    margin: 28px 0 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid #eeeeee;
    color: #1a1a1a;
    line-height: 1.35;
  }

  .editor-container :global(.ck-content h3) {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 8px;
    color: #1a1a1a;
    line-height: 1.4;
  }

  .editor-container :global(.ck-content h4),
  .editor-container :global(.ck-content h5),
  .editor-container :global(.ck-content h6) {
    font-size: 16px;
    font-weight: 600;
    margin: 20px 0 6px;
    color: #2a2a2a;
    line-height: 1.4;
  }

  .editor-container :global(.ck-content p) {
    margin: 0 0 12px;
  }

  .editor-container :global(.ck-content blockquote) {
    border-left: 3px solid #1a73e8;
    margin: 16px 0;
    padding: 8px 16px;
    color: #555;
    background: #f8f9fa;
    border-radius: 0 4px 4px 0;
  }

  .editor-container :global(.ck-content blockquote p) {
    margin: 4px 0;
  }

  .editor-container :global(.ck-content table) {
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
    font-size: 14px;
  }

  .editor-container :global(.ck-content th),
  .editor-container :global(.ck-content td) {
    border: 1px solid #dadce0;
    padding: 10px 14px;
    text-align: left;
  }

  .editor-container :global(.ck-content th) {
    background: #f1f3f4;
    font-weight: 600;
    color: #1a1a1a;
  }

  .editor-container :global(.ck-content tr:nth-child(even)) {
    background: #fafafa;
  }

  .editor-container :global(.ck-content code) {
    background: #f1f3f4;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    color: #d63384;
  }

  .editor-container :global(.ck-content pre) {
    background: #f8f9fa;
    padding: 16px 20px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 16px 0;
    border: 1px solid #e8eaed;
  }

  .editor-container :global(.ck-content pre code) {
    background: none;
    padding: 0;
    border-radius: 0;
    font-size: 13px;
    line-height: 1.5;
    color: inherit;
  }

  .editor-container :global(.ck-content a) {
    color: #1a73e8;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .editor-container :global(.ck-content a:hover) {
    color: #1558b0;
  }

  .editor-container :global(.ck-content hr) {
    border: none;
    border-top: 1px solid #dadce0;
    margin: 28px 0;
  }

  .editor-container :global(.ck-content img) {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
    margin: 12px 0;
  }

  .editor-container :global(.ck-content ul),
  .editor-container :global(.ck-content ol) {
    padding-left: 28px;
    margin: 0 0 12px;
  }

  .editor-container :global(.ck-content li) {
    margin: 4px 0;
  }

  .editor-container :global(.ck-content li > ul),
  .editor-container :global(.ck-content li > ol) {
    margin: 4px 0;
  }

  /* ===========================================
     Loading Placeholder
     =========================================== */

  .loading-placeholder {
    padding: 24px 0;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .loading-shimmer {
    height: 16px;
    width: 100%;
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 0.05) 25%,
      rgba(255, 255, 255, 0.15) 50%,
      rgba(255, 255, 255, 0.05) 75%
    );
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 4px;
  }

  .loading-shimmer.short {
    width: 60%;
  }

  .loading-shimmer.medium {
    width: 80%;
  }

  @keyframes shimmer {
    0% {
      background-position: 200% 0;
    }
    100% {
      background-position: -200% 0;
    }
  }

  /* ===========================================
     Error State
     =========================================== */

  .load-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 48px 24px;
    color: var(--color-font-secondary);
    text-align: center;
    gap: 8px;
  }

  .load-error p {
    margin: 0;
    font-size: 15px;
  }

  .error-detail {
    font-size: 13px;
    opacity: 0.7;
  }

  /* ===========================================
     Responsive: Mobile
     =========================================== */

  @media (max-width: 900px) {
    .editor-container :global(.ck.ck-editor__editable) {
      font-size: 14px;
    }

    .editor-container :global(.ck-content h1) {
      font-size: 22px;
    }

    .editor-container :global(.ck-content h2) {
      font-size: 18px;
    }

    .editor-container :global(.ck-content h3) {
      font-size: 16px;
    }
  }
</style>
