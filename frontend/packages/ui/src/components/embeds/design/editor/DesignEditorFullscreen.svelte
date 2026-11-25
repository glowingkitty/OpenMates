<!-- figma-visual-proof: not-required. Original OpenMates preview with browser proof. -->
<script lang="ts">
  import { untrack, type Snippet } from 'svelte';
  import UnifiedEmbedFullscreen from '../../UnifiedEmbedFullscreen.svelte';
  import EmbedIconButton from '../../shared/EmbedIconButton.svelte';
  import EmbedZoomControls from '../../shared/EmbedZoomControls.svelte';
  import DesignCanvas from './DesignCanvas.svelte';
  import DesignLayers from './DesignLayers.svelte';
  import DesignProperties from './DesignProperties.svelte';
  import DesignPageThumbnail from './DesignPageThumbnail.svelte';
  import { DEFAULT_LAYER_COLOR, DESIGN_PAGE_CAP, PREVIEW_LAYER_CAP, type DesignDocument, type DesignLayer } from './designDocument';

  interface Props {
    document: DesignDocument;
    embedId?: string;
    owningChatId?: string;
    readOnly?: boolean;
    readImage?: (id: string) => Promise<ImageBitmap | null>;
    initialMode?: 'view' | 'edit';
    revision?: { version: number; save: (baseVersion: number, document: DesignDocument) => Promise<void> };
    versionNumber?: number;
    versionHistory?: Snippet;
    assistantTools?: Snippet;
    onClose: () => void;
  }

  let { document: initialDocument, embedId, owningChatId, initialMode = 'view', readOnly = false, readImage, revision, versionNumber, versionHistory, assistantTools, onClose }: Props = $props();
  let document = $state.raw(untrack(() => initialDocument));
  let editing = $state(untrack(() => !readOnly && initialMode === 'edit'));
  let editingVersion = $state<number>();
  let editStart = $state.raw<DesignDocument>();
  let saving = $state(false);
  let saveError = $state('');
  let pageIndex = $state(0);
  let selectedId = $state<string | null>(null);
  let mobilePanel = $state<'layers' | 'properties' | null>(null);
  let pagesOpen = $state(false);
  let clipboardOpen = $state(false);
  let copied = $state.raw<DesignLayer | null>(null);
  let history = $state.raw<{ past: Revision[]; future: Revision[] }>({ past: [], future: [] });
  let zoom = $state(1);
  let canvas: DesignCanvas | undefined = $state();
  let properties: DesignProperties | undefined = $state();
  let root: HTMLElement;

  interface Revision {
    pageBefore: number;
    pageAfter: number;
    before: DesignDocument;
    after: DesignDocument;
    selectionBefore: string | null;
    selectionAfter: string | null;
  }

  const activePage = $derived(document.pages[pageIndex]);
  const selected = $derived(activePage.layers.find((layer) => layer.id === selectedId) ?? null);
  const canPaste = $derived(copied !== null && activePage.layers.length < PREVIEW_LAYER_CAP);
  const canAddLayer = $derived(revision && activePage.layers.length < PREVIEW_LAYER_CAP);

  $effect(() => {
    const latest = initialDocument;
    if (readOnly && editing) {
      editing = false;
      history = { past: [], future: [] };
      select(null);
    }
    if (!editing && (revision || readOnly)) {
      document = latest;
      pageIndex = Math.min(untrack(() => pageIndex), latest.pages.length - 1);
    }
  });

  function select(id: string | null) {
    selectedId = id;
    if (id === null && mobilePanel === 'properties') mobilePanel = null;
  }

  function commitDocument(next: DesignDocument, nextPage: number, nextSelection: string | null) {
    if (saving || readOnly) return;
    const change = { pageBefore: pageIndex, pageAfter: nextPage, before: document, after: next,
      selectionBefore: selectedId, selectionAfter: nextSelection };
    document = next;
    pageIndex = nextPage;
    history = { past: [...history.past.slice(-59), change], future: [] };
    select(nextSelection);
  }

  function commit(layers: DesignLayer[], nextSelection = selectedId) {
    const pages = document.pages.map((page, i) => i === pageIndex ? { ...page, layers } : page);
    commitDocument({ ...document, pages }, pageIndex, nextSelection);
  }

  function changeLayer(layer: DesignLayer) {
    const before = activePage.layers.find((candidate) => candidate.id === layer.id);
    if (!before || JSON.stringify(before) === JSON.stringify(layer)) return;
    commit(activePage.layers.map((candidate) => candidate.id === layer.id ? layer : candidate));
  }

  function reorder(direction: number) {
    const layers = [...activePage.layers];
    const index = layers.findIndex((layer) => layer.id === selectedId);
    const to = index + direction;
    if (index === -1 || layers[index].locked || to < 0 || to >= layers.length) return;
    [layers[index], layers[to]] = [layers[to], layers[index]];
    commit(layers);
  }

  function undo() {
    if (saving) return;
    const revision = history.past.at(-1);
    if (!revision) return;
    document = revision.before;
    pageIndex = revision.pageBefore;
    select(revision.selectionBefore);
    history = { past: history.past.slice(0, -1), future: [...history.future, revision] };
  }

  function redo() {
    if (saving) return;
    const revision = history.future.at(-1);
    if (!revision) return;
    document = revision.after;
    pageIndex = revision.pageAfter;
    select(revision.selectionAfter);
    history = { past: [...history.past, revision], future: history.future.slice(0, -1) };
  }

  function copy() {
    if (!selected) return;
    copied = selected;
    clipboardOpen = false;
  }

  function paste() {
    if (!copied || !canPaste) return;
    const clone = { ...copied, id: crypto.randomUUID(),
      x: Math.max(0, Math.min(activePage.width - 24, copied.x + 16)),
      y: Math.max(0, Math.min(activePage.height - 24, copied.y + 16)), locked: false, hidden: false };
    commit([...activePage.layers, clone], clone.id);
    clipboardOpen = false;
  }

  function addLayer(kind: 'text' | 'shape') {
    if (!canAddLayer) return;
    const base = {
      id: crypto.randomUUID(), x: activePage.width / 10, y: activePage.height / 10,
      width: Math.max(1, Math.min(240, activePage.width * 0.8)),
      height: Math.max(1, Math.min(72, activePage.height * 0.8)),
      rotation: 0, color: DEFAULT_LAYER_COLOR
    };
    const layer: DesignLayer = kind === 'text'
      ? { ...base, kind, name: 'Text', text: 'Your text', font: 'Sans', fontSize: 24, weight: 500 }
      : { ...base, kind, name: 'Rectangle', shape: 'rectangle' };
    commit([...activePage.layers, layer], layer.id);
    clipboardOpen = false;
  }

  function deleteLayer() {
    if (selected && !selected.locked) commit(activePage.layers.filter((layer) => layer.id !== selectedId), null);
    clipboardOpen = false;
  }

  function addPage() {
    if (document.pages.length >= DESIGN_PAGE_CAP) return;
    const blank = { ...activePage, id: crypto.randomUUID(), name: `Page ${document.pages.length + 1}`, layers: [] };
    const pages = [...document.pages, blank];
    commitDocument({ ...document, pages }, pages.length - 1, null);
    pagesOpen = false;
  }

  function deletePage() {
    if (document.pages.length <= 1) return;
    const pages = document.pages.filter((page) => page.id !== activePage.id);
    commitDocument({ ...document, pages }, Math.min(pageIndex, pages.length - 1), null);
    pagesOpen = false;
  }

  async function toggleMode() {
    if (readOnly || saving) return;
    saveError = '';
    if (!editing) {
      editingVersion = revision?.version;
      editStart = document;
      history = { past: [], future: [] };
      editing = true;
      return;
    }
    if (revision && editingVersion !== undefined && document !== editStart) {
      saving = true;
      try {
        await revision.save(editingVersion, document);
      } catch (error) {
        const code = (error as { code?: string } | null)?.code;
        saveError = code === 'embed_version_conflict'
          ? 'A newer version was saved. Reopen the design before applying your changes.'
          : code === 'design_scene_invalid'
            ? 'This edit exceeds the supported design limits.'
            : 'The design could not be saved. Your edits are still open.';
        return;
      } finally {
        saving = false;
      }
    }
    editing = false;
    editStart = undefined;
    select(null);
    mobilePanel = null;
    clipboardOpen = false;
  }

  function openPage(index: number) {
    if (index !== pageIndex) {
      pageIndex = index;
      select(null);
    }
    pagesOpen = false;
  }

  function escape() {
    if (pagesOpen || clipboardOpen || mobilePanel || (editing && selectedId !== null)) {
      if (pagesOpen) pagesOpen = false;
      else if (clipboardOpen) clipboardOpen = false;
      else if (mobilePanel) mobilePanel = null;
      else select(null);
      return true;
    }
    return false;
  }

  function handleKeys(event: KeyboardEvent) {
    if (!editing || !root?.contains(event.target as Node) ||
      (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable]'))) return;
    const modifier = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (modifier && key === 'z') {
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
    } else if (modifier && key === 'y') {
      event.preventDefault();
      redo();
    } else if (modifier && key === 'c' && selected && !window.getSelection()?.toString()) {
      event.preventDefault();
      copy();
    } else if (modifier && key === 'v' && canPaste) {
      event.preventDefault();
      paste();
    } else if (selected && !selected.locked && !modifier && ['arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(key)) {
      event.preventDefault();
      const step = event.shiftKey ? 10 : 1;
      const x = key === 'arrowleft' ? -step : key === 'arrowright' ? step : 0;
      const y = key === 'arrowup' ? -step : key === 'arrowdown' ? step : 0;
      changeLayer({ ...selected, x: selected.x + x, y: selected.y + y });
    }
  }

  function editText(id: string) {
    select(id);
    mobilePanel = 'properties';
    void properties?.focusText();
  }
</script>

<svelte:window onkeydown={handleKeys} />

<UnifiedEmbedFullscreen appId="design" {onClose} showShare={false} currentEmbedId={embedId} {owningChatId}
  embedHeaderTitle={document.title} embedHeaderSubtitle={`${activePage.width} × ${activePage.height}`}
  testId="design-fullscreen" contentLayout="app-home"
  onEdit={readOnly ? undefined : toggleMode} editActive={editing} editBusy={saving} editToggleOnly={!revision} editPlacement="close" editTestId="design-mode" reportInMore
  editLabel={editing ? revision ? 'Save design' : 'View design' : 'Edit design'} escapeScope={{ consume: escape }}>
  {#snippet content()}
    <div class="workspace" class:editing class:assistant-tools={!!assistantTools && !editing} bind:this={root} data-testid="design-workspace" data-mode={editing ? 'edit' : 'view'}
      data-selection={selectedId} data-layers={activePage.layers.length} data-version={versionNumber}>
      {#if assistantTools && !editing}
        <div class="assistant-toolbar">{@render assistantTools()}</div>
      {/if}
      {#if saveError}
        <p class="save-error" role="alert" data-testid="design-save-error">{saveError}</p>
      {/if}
      {#if editing}
        <div class="layers panel-slot" class:open={mobilePanel === 'layers'}>
          <DesignLayers layers={activePage.layers} {selectedId} onSelect={select} onChange={changeLayer}
            onOrder={reorder} onClose={() => mobilePanel = null} />
        </div>
      {/if}

      <div class="canvas-area">
        {#key activePage.id}
          <DesignCanvas bind:this={canvas} page={activePage} {editing} selection={selected} bind:zoom
            onSelect={select} onCommit={changeLayer} onDoubleClick={editText} {readImage} />
        {/key}

        {#if document.pages.length > 1 || editing && revision}
          <div class="pages">
            <button type="button" class="page-toggle" aria-expanded={pagesOpen} aria-controls="design-pages"
              data-testid="design-page-chooser" onclick={() => pagesOpen = !pagesOpen}>
              {activePage.name} <span>{pageIndex + 1} / {document.pages.length} ▾</span>
            </button>
            {#if pagesOpen}
              <div class="page-menu" id="design-pages" aria-label="Design pages">
                {#each document.pages as page, index (page.id)}
                  <button type="button" aria-current={pageIndex === index ? 'page' : undefined} data-testid={`design-page-${page.id}`} onclick={() => openPage(index)}>
                    <DesignPageThumbnail {page} />
                    {page.name}
                  </button>
                {/each}
                {#if editing && revision}
                  <button type="button" data-testid="design-add-page" disabled={document.pages.length >= DESIGN_PAGE_CAP} onclick={addPage}>Add page</button>
                  <button type="button" data-testid="design-delete-page" disabled={document.pages.length <= 1} onclick={deletePage}>Remove page</button>
                {/if}
              </div>
            {/if}
          </div>
        {/if}

        <div class="tools" role="toolbar" aria-label="Design tools">
          {#if editing}
            <div class="mobile-tools">
              <EmbedIconButton icon="menu" label="Layers" testId="design-show-layers" pressed={mobilePanel === 'layers'}
                onclick={() => mobilePanel = mobilePanel === 'layers' ? null : 'layers'} />
              <EmbedIconButton icon="settings" label="Properties" testId="design-show-properties" pressed={mobilePanel === 'properties'} disabled={!selected}
                onclick={() => mobilePanel = mobilePanel === 'properties' ? null : 'properties'} />
              <!-- ui-control-visibility: allow shared icon buttons expose their testId. -->
            </div>
            <EmbedIconButton icon="back" label="Undo" testId="design-undo" disabled={!history.past.length} onclick={undo} />
            <EmbedIconButton icon="back" flip label="Redo" testId="design-redo" disabled={!history.future.length} onclick={redo} />
            <div class="clipboard" data-testid="design-clipboard-controls">
              <EmbedIconButton icon="more" label={revision ? 'Layer actions' : 'Clipboard'} testId="design-clipboard-toggle" expanded={clipboardOpen} controls="design-clipboard" disabled={!revision && !selected && !canPaste}
                onclick={() => clipboardOpen = !clipboardOpen} />
              {#if clipboardOpen}
                <div class="clipboard-menu" id="design-clipboard">
                  <button type="button" data-testid="design-copy-layer" onclick={copy} disabled={!selected}>Copy layer</button>
                  <button type="button" data-testid="design-paste-layer" onclick={paste} disabled={!canPaste}>Paste layer</button>
                  {#if revision}
                    <button type="button" data-testid="design-add-text" onclick={() => addLayer('text')} disabled={!canAddLayer}>Add text</button>
                    <button type="button" data-testid="design-add-rectangle" onclick={() => addLayer('shape')} disabled={!canAddLayer}>Add rectangle</button>
                    <button type="button" data-testid="design-delete-layer" onclick={deleteLayer} disabled={!selected || selected.locked}>Remove layer</button>
                  {/if}
                  {#if copied && !canPaste}<span>Layer cap reached ({PREVIEW_LAYER_CAP})</span>{/if}
                </div>
              {/if}
            </div>
            <span class="divider" aria-hidden="true"></span>
          {/if}
          <div class="zoom">
            <EmbedZoomControls zoomOut={() => canvas?.adjustZoom(1 / 1.25)} zoomIn={() => canvas?.adjustZoom(1.25)}
              zoomOutTestId="design-zoom-out" zoomInTestId="design-zoom-in" resetTestId="design-fit"
              resetZoom={() => canvas?.fit()} zoomLabel={`${Math.round(zoom * 100)}%`}
              zoomOutDisabled={zoom <= 0.1} zoomInDisabled={zoom >= 4} />
          </div>
        </div>
      </div>

      {#if editing}
        <div class="properties panel-slot" class:open={mobilePanel === 'properties'}>
          <DesignProperties bind:this={properties} layer={selected} onChange={changeLayer} onClose={() => mobilePanel = null} />
        </div>
      {/if}
    </div>
    {#if !editing && versionHistory}{@render versionHistory()}{/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .save-error {
    position: absolute; z-index: 2; inset: 0 0 auto; width: max-content; max-width: calc(100% - 24px);
    margin: var(--spacing-6) auto; padding: var(--spacing-4) var(--spacing-6);
    border-radius: var(--radius-3); background: var(--color-grey-0);
    box-shadow: var(--shadow-md); color: var(--color-font-primary); text-align: center;
  }
  .workspace {
    flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr);
    position: relative; isolation: isolate; color: var(--color-font-primary);
  }
  .workspace.assistant-tools { grid-template-rows: auto minmax(0, 1fr); }
  .assistant-toolbar { grid-column: 1 / -1; background: var(--color-grey-0); }
  .workspace.editing { grid-template-columns: minmax(172px, 19%) minmax(0, 1fr) minmax(185px, 20%); }
  .panel-slot { background: var(--color-grey-0); min-width: 0; min-height: 0; }
  .layers { border-right: 1px solid var(--color-grey-25); }
  .properties { border-left: 1px solid var(--color-grey-25); }
  .canvas-area {
    position: relative; min-height: 0; min-width: 0; overflow: hidden;
    background-color: var(--color-grey-20);
    background-image: radial-gradient(color-mix(in srgb, var(--color-grey-40) 56%, var(--color-grey-20)) .8px, transparent 1px);
    background-size: 16px 16px;
  }
  .tools {
    position: absolute; left: 50%; bottom: 15px; transform: translateX(-50%);
    display: flex; align-items: center; gap: 5px; z-index: 3;
    padding: 5px 7px; border-radius: var(--radius-full); white-space: nowrap;
    background: var(--color-grey-0); box-shadow: var(--shadow-lg);
  }
  .tools :global(.embed-icon-button) { width: 38px; height: 38px; padding: 8px; }
  .divider { width: 1px; height: 24px; margin-inline: 3px; background: var(--color-grey-25); }
  .zoom :global(.doc-zoom-bar) { position: static; margin: 0; padding: 0; }
  .zoom :global(.doc-zoom-bar-inner) { background: transparent; box-shadow: none; padding: 0; gap: 2px; }
  .zoom :global(button) { margin: 0; filter: none; }
  .zoom :global(.doc-zoom-btn) { min-width: 0; }
  .zoom :global(.doc-zoom-level) { min-width: 42px; padding-inline: 6px; }
  .mobile-tools { display: none; }
  .pages { position: absolute; top: 14px; left: 14px; z-index: 2; }
  .page-toggle, .page-menu, .clipboard-menu {
    background: var(--color-grey-0); color: inherit;
    border: 1px solid var(--color-grey-25); box-shadow: var(--shadow-lg);
  }
  .page-toggle {
    padding: 8px 12px; min-width: 0; min-height: 42px; margin: 0; filter: none;
    border-radius: var(--radius-full); font: inherit; font-size: var(--font-size-xs); cursor: pointer;
  }
  .page-toggle span { color: var(--color-font-tertiary); margin-left: 6px; }
  .page-menu {
    display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; padding: 5px; border-radius: var(--radius-3);
    max-width: calc(100cqw - 28px); max-height: min(55vh, 300px); overflow: auto;
  }
  .page-menu button {
    min-width: 67px; height: auto; margin: 0; filter: none; border: 0; display: grid; justify-items: center; gap: 5px; padding: 6px;
    background: var(--color-grey-10); color: inherit; border-radius: var(--radius-3); font-size: var(--font-size-xxs); cursor: pointer;
  }
  .page-menu button[aria-current='page'] { background: color-mix(in srgb, var(--color-primary-start) 18%, var(--color-grey-0)); }
  .clipboard { position: relative; }
  .clipboard-menu {
    position: absolute; bottom: 45px; left: 50%; transform: translateX(-50%);
    display: grid; min-width: 130px; padding: 5px; border-radius: var(--radius-3);
  }
  .clipboard-menu button {
    border: 0; border-radius: var(--radius-3); background: var(--color-grey-0); color: inherit;
    margin: 0; filter: none; padding: 9px; font: inherit; font-size: var(--font-size-xs); cursor: pointer;
  }
  .clipboard-menu button:hover { background: var(--color-grey-20); }
  .clipboard-menu button:disabled { opacity: .45; cursor: default; }
  .clipboard-menu span { font-size: var(--font-size-tiny); padding: 6px; }

  @container fullscreen (max-width: 740px) {
    .workspace.editing { grid-template-columns: minmax(0, 1fr); }
    .mobile-tools { display: flex; gap: 3px; }
    .tools { gap: 3px; bottom: 10px; padding: 4px; }
    .tools :global(.embed-icon-button) { width: 42px; height: 42px; }
    .zoom :global(.doc-zoom-btn) { width: 32px; height: 42px; }
    .divider { margin-inline: 1px; }
    .panel-slot {
      display: none; position: absolute; z-index: 2; inset: auto 7px 67px; height: min(320px, 53%);
      border: 1px solid var(--color-grey-25); border-radius: var(--radius-7);
      box-shadow: var(--shadow-lg);
    }
    .panel-slot.open { display: block; }
  }
  @container fullscreen (max-width: 340px) {
    .tools :global(.embed-icon-button) { width: 36px; height: 42px; padding: 6px; }
    .zoom :global(.doc-zoom-btn) { width: 28px; }
  }
</style>
