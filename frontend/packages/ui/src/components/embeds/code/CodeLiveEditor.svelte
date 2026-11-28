<!--
  Live code editor (flag live_collaboration): CodeMirror 6 over a Y.Text "content" mirror
  (y-codemirror.next). The mirror only exchanges opaque update bytes with the Rust core
  through the live item client; merging, saving and access are the core's. Remote cursors
  render from the core's presence. No Save button: the core saves; the header Edit
  button enters and leaves editing. Keeps the selectors of CodeEditor.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { EditorState, StateEffect, StateField, RangeSetBuilder } from '@codemirror/state';
  import { Decoration, EditorView, keymap, lineNumbers, type DecorationSet } from '@codemirror/view';
  import { defaultKeymap, indentWithTab } from '@codemirror/commands';
  import { yCollab, yUndoManagerKeymap } from 'y-codemirror.next';
  import * as Y from 'yjs';
  import { text } from '@repo/ui';
  import EmbedIconButton from '../shared/EmbedIconButton.svelte';
  import { liveItemClient } from '../../../services/live/liveItemClient';
  import { bindLiveMirror, type LiveMirror } from '../../../services/live/liveMirror';
  import type { LiveItemClient, LivePeer, LiveStatus } from '../../../services/live/liveItemTypes';
  import { peerMate } from '../../../services/live/liveSurface';
  import { liveCodeLanguage } from './liveCodeLanguage';

  interface Props {
    itemId: string;
    projectId?: string;
    teamId?: string;
    /** File name or language label, used for highlighting only. */
    filename?: string;
    self: Pick<LivePeer, 'display_name' | 'color'>;
    onCancel: () => void;
    error?: string;
    client?: LiveItemClient;
    status?: LiveStatus;
    peers?: LivePeer[];
  }

  let { itemId, projectId, teamId, filename, self, onCancel, error = '', client = liveItemClient(), status = $bindable('saving'), peers = $bindable([]) }: Props = $props();

  let host: HTMLDivElement | undefined = $state(undefined);
  let view: EditorView | null = null;
  let mirror: LiveMirror | null = null;
  let readOnly = $derived(status === 'read_only' || status === 'access_revoked');

  /** Line ranges (1-based, inclusive) where an assistant works, with its colour and name. */
  interface MateRange { from: number; to: number; color: string; name: string }
  const setMateRanges = StateEffect.define<MateRange[]>();
  const mateField = StateField.define<DecorationSet>({
    create: () => Decoration.none,
    update(deco, tr) {
      for (const effect of tr.effects) {
        if (!effect.is(setMateRanges)) continue;
        const builder = new RangeSetBuilder<Decoration>();
        const label = (name: string) => $text('embed_user_edits.live_editing_here', { values: { name } });
        for (const r of [...effect.value].sort((a, b) => a.from - b.from)) {
          for (let n = r.from; n <= Math.min(r.to, tr.state.doc.lines); n++) {
            const line = tr.state.doc.line(n);
            builder.add(line.from, line.from, Decoration.line({
              attributes: {
                class: 'cm-mate-line',
                'data-testid': 'code-mate-line',
                style: `background: color-mix(in srgb, ${r.color} 18%, transparent); box-shadow: inset 3px 0 0 ${r.color};`,
                ...(n === r.from ? { 'data-mate-label': label(r.name) } : {}),
              },
            }));
          }
        }
        return builder.finish();
      }
      return deco.map(tr.changes);
    },
    provide: (f) => EditorView.decorations.from(f),
  });

  // "<mate> is editing here": highlight the lines of each assistant peer's selection.
  $effect(() => {
    const current = peers;
    if (!view || !mirror) return;
    const ytext = mirror.doc.getText('content');
    const ranges: MateRange[] = [];
    for (const peer of current) {
      const name = peerMate(peer);
      const cursor = peer.kind_cursor as { anchor?: unknown; head?: unknown } | null | undefined;
      if (!name || !cursor?.anchor || !cursor.head) continue;
      const a = Y.createAbsolutePositionFromRelativePosition(Y.createRelativePositionFromJSON(cursor.anchor), mirror.doc);
      const h = Y.createAbsolutePositionFromRelativePosition(Y.createRelativePositionFromJSON(cursor.head), mirror.doc);
      if (!a || !h || a.type !== ytext || h.type !== ytext) continue;
      const doc = view.state.doc;
      const l1 = doc.lineAt(Math.min(a.index, doc.length)).number;
      const l2 = doc.lineAt(Math.min(h.index, doc.length)).number;
      ranges.push({ from: Math.min(l1, l2), to: Math.max(l1, l2), color: peer.color, name });
    }
    view.dispatch({ effects: setMateRanges.of(ranges) });
  });

  onMount(() => {
    if (!host) return;
    mirror = bindLiveMirror(client, itemId, 'code', self, (s) => { status = s; }, (p) => { peers = p; }, projectId, teamId);
    const ytext = mirror.doc.getText('content');
    view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: ytext.toString(),
        extensions: [
          lineNumbers(),
          mateField,
          keymap.of([...yUndoManagerKeymap, indentWithTab, ...defaultKeymap]),
          ...liveCodeLanguage(filename),
          yCollab(ytext, mirror.awareness, { undoManager: new Y.UndoManager(ytext) }),
          EditorView.contentAttributes.of({
            'data-testid': 'code-editor-textarea',
            'aria-label': $text('app_skills.code.editor.label'),
            spellcheck: 'false',
            autocapitalize: 'off',
          }),
        ],
      }),
    });
    view.focus();
    return () => {
      view?.destroy();
      mirror?.destroy();
      view = null;
      mirror = null;
    };
  });

  $effect(() => {
    if (!view) return;
    view.contentDOM.contentEditable = readOnly ? 'false' : 'true';
  });

  /** Leaves edit mode; the core has already saved every change. */
  export async function save(): Promise<void> { onCancel(); }
</script>

<div class="code-editor" data-testid="code-editor" data-live="true" data-status={status}>
  <div class="code-editor-bar">
    <EmbedIconButton icon="close" label={$text('common.cancel')} testId="code-editor-cancel" onclick={onCancel} />
  </div>
  {#if error}
    <div class="code-editor-error" data-testid="code-editor-error" role="alert"><span>{error}</span></div>
  {/if}
  <div class="code-editor-body" bind:this={host}></div>
</div>

<style>
  .code-editor { display: flex; flex-direction: column; gap: var(--spacing-4); min-height: 320px; height: 100%; }
  .code-editor-bar { display: flex; align-items: center; justify-content: flex-end; gap: var(--spacing-4); }
  .code-editor-error { display: flex; align-items: center; gap: var(--spacing-4); padding: var(--spacing-4) var(--spacing-6); border-radius: var(--radius-3); background: var(--color-grey-10); color: var(--color-error); font-size: var(--font-size-small); }
  .code-editor-body { flex: 1; min-height: 0; border-radius: var(--radius-3); background: var(--color-grey-10); overflow: auto; }
  .code-editor-body :global(.cm-editor) { height: 100%; background: transparent; color: var(--color-font-primary); font-family: var(--font-family-mono, ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace); font-size: var(--font-size-small); }
  .code-editor-body :global(.cm-editor.cm-focused) { outline: 2px solid var(--color-primary-start); outline-offset: -2px; }
  .code-editor-body :global(.cm-gutters) { background: transparent; border: 0; color: var(--color-font-tertiary); }
  .code-editor-body :global(.cm-mate-line[data-mate-label])::before { content: attr(data-mate-label); float: right; padding: 0 var(--spacing-3); font-size: 11px; color: var(--color-font-secondary); }
  .code-editor-body :global(.cm-scroller) { line-height: 1.5; }
</style>
