// frontend/packages/ui/src/components/enter_message/services/liveTranscriptInsertion.ts
//
// Streams a realtime dictation transcript into the composer as ordinary,
// editable text. The realtime service reports the cumulative transcript; only
// its not-yet-inserted suffix is placed at the editor's current selection and
// the caret advances behind it. Moving the caret therefore redirects the next
// dictated words to that spot (a new "segment").
//
// When the correction pass finishes, a single untouched segment is replaced by
// the corrected transcript. Once the user redirected dictation or edited the
// dictated text, the corrected whole-recording text can no longer be mapped
// onto the pieces, so the live text the user already arranged is kept as-is.

import type { Editor, JSONContent } from '@tiptap/core';
import { TextSelection, type Transaction } from '@tiptap/pm/state';
import type { EditorView } from '@tiptap/pm/view';
import { setRecordingTranscriptProcessing, type TranscriptRange } from '../extensions/RecordingTranscriptProcessing';

/** Transaction meta flag for live dictation writes (lets hosts tell them apart from typing). */
export const LIVE_TRANSCRIPT_META = 'openmatesLiveTranscript';

interface Segment {
    from: number;
    to: number;
    /** Exact text this controller wrote into [from, to); hard breaks are "\n". */
    text: string;
    /** Separator spaces added outside [from, to) so dictation does not glue onto neighbours. */
    spaceBefore: boolean;
    spaceAfter: boolean;
}

export type LiveTranscriptCorrectionOutcome = 'replaced' | 'inserted' | 'kept';

export interface LiveTranscriptController {
    /** Apply the latest cumulative transcript. Returns true when text was inserted. */
    apply(cumulativeTranscript: string): boolean;
    /** True once any dictated text is in the document. */
    hasText(): boolean;
    /** Current dictated ranges (mapped through every later edit). */
    ranges(): TranscriptRange[];
    /** Show or clear the processing shimmer on the dictated ranges. */
    setProcessing(active: boolean): void;
    /** Reconcile the corrected transcript with the dictated text. */
    applyCorrection(correctedTranscript: string): LiveTranscriptCorrectionOutcome;
    /** Remove untouched dictated text (used when the recording is cancelled). */
    discard(): void;
    /** Stop tracking editor transactions. */
    destroy(): void;
}

const NO_SPACE_BEFORE = /^[\s.,!?;:)\]}%…]/;
const NO_SPACE_AFTER = /[\s([{]$/;

export function transcriptToContent(text: string): JSONContent[] {
    const content: JSONContent[] = [];
    text.split(/\r\n?|\n/).forEach((line, index) => {
        if (index > 0) content.push({ type: 'hardBreak' });
        if (line) content.push({ type: 'text', text: line });
    });
    return content;
}

/** Normalize line endings so stored segment text matches `textBetween(..., '\n')`. */
function normalize(text: string): string {
    return text.replace(/\r\n?/g, '\n');
}

export function createLiveTranscriptController(editor: Editor): LiveTranscriptController {
    const segments: Segment[] = [];
    let consumed = '';
    let processing = false;
    let destroyed = false;

    const mapSegments = ({ transaction }: { transaction: Transaction }) => {
        if (!transaction.docChanged) return;
        for (const segment of segments) {
            segment.from = transaction.mapping.map(segment.from, 1);
            segment.to = Math.max(segment.from, transaction.mapping.map(segment.to, -1));
        }
    };
    editor.on('transaction', mapSegments);

    const alive = () => !destroyed && !editor.isDestroyed;

    const textAt = (from: number, to: number) => {
        const size = editor.state.doc.content.size;
        if (from < 0 || to > size || from > to) return '';
        return editor.state.doc.textBetween(from, to, '\n', '\n');
    };

    // ProseMirror pulls DOM selection changes in asynchronously. A caret the
    // user just tapped must win over the stale state selection, so flush the
    // view's (internal, untyped) DOM observer before choosing the insert point.
    const syncDomSelection = () => {
        const view = editor.view as EditorView & { domObserver?: { flush(): void } };
        if (view.hasFocus()) view.domObserver?.flush();
    };

    // Recording starts while the editor still has focus: capture the caret the
    // user placed (e.g. with arrow keys) before the recorder takes focus.
    syncDomSelection();

    const untouched = (segment: Segment) => textAt(segment.from, segment.to) === segment.text;

    /** Insert `text` replacing [from, to); returns the new range of `text` itself. */
    const write = (from: number, to: number, text: string, newSegment: boolean): Segment | null => {
        let body = normalize(text);
        let spaceBefore = false;
        let spaceAfter = false;
        if (newSegment) {
            const before = textAt(Math.max(0, from - 1), from);
            const after = textAt(to, Math.min(editor.state.doc.content.size, to + 1));
            body = body.replace(/^\s+/, '');
            if (!body) return null;
            spaceBefore = !!before && !NO_SPACE_AFTER.test(before) && !NO_SPACE_BEFORE.test(body);
            spaceAfter = !!after && !NO_SPACE_BEFORE.test(after) && !/\s$/.test(body);
        }
        if (!body) return null;
        const inserted = `${spaceBefore ? ' ' : ''}${body}${spaceAfter ? ' ' : ''}`;
        const bodyFrom = from + (spaceBefore ? 1 : 0);
        const bodyTo = bodyFrom + body.length;
        const ok = editor.chain()
            .command(({ tr }) => { tr.setMeta(LIVE_TRANSCRIPT_META, true); return true; })
            .insertContentAt({ from, to }, transcriptToContent(inserted), {
                updateSelection: false,
                parseOptions: { preserveWhitespace: 'full' },
            })
            .setTextSelection(bodyTo)
            .scrollIntoView()
            .run();
        if (!ok) return null;
        return { from: bodyFrom, to: bodyTo, text: body, spaceBefore, spaceAfter };
    };

    const refreshProcessing = () => {
        if (!alive()) return;
        const ranges = processing ? segments.map(({ from, to }) => ({ from, to })) : [];
        editor.view.dispatch(setRecordingTranscriptProcessing(editor.state.tr, ranges));
    };

    return {
        apply(cumulativeTranscript) {
            if (!alive()) return false;
            const transcript = normalize(cumulativeTranscript);
            // Realtime deltas only append. A finalized transcript that diverges
            // from what was streamed is reconciled by the correction step.
            if (!transcript.startsWith(consumed)) return false;
            const delta = transcript.slice(consumed.length);
            if (!delta) return false;
            syncDomSelection();
            const selection = editor.state.selection;
            // Dictation replaces selected text like typing does, but never a
            // selected embed or other node.
            const from = selection instanceof TextSelection ? selection.from : selection.to;
            const { to, empty } = selection;
            const last = segments[segments.length - 1];
            const continues = !!last && empty && to === last.to && untouched(last);
            const written = write(from, to, delta, !continues);
            consumed = transcript;
            if (!written) return false;
            if (continues) {
                last.to = written.to;
                last.text += written.text;
            } else {
                segments.push(written);
            }
            if (processing) refreshProcessing();
            return true;
        },
        hasText() {
            return segments.some((segment) => segment.to > segment.from);
        },
        ranges() {
            return segments.map(({ from, to }) => ({ from, to }));
        },
        setProcessing(active) {
            if (processing === active) return;
            processing = active;
            refreshProcessing();
        },
        applyCorrection(correctedTranscript) {
            if (!alive()) return 'kept';
            const corrected = normalize(correctedTranscript).trim();
            if (!corrected) return 'kept';
            if (segments.length === 0) {
                syncDomSelection();
                const selection = editor.state.selection;
                const from = selection instanceof TextSelection ? selection.from : selection.to;
                const written = write(from, selection.to, corrected, true);
                if (!written) return 'kept';
                segments.push(written);
                return 'inserted';
            }
            const [only] = segments;
            if (segments.length !== 1 || !untouched(only)) return 'kept';
            if (only.text === corrected) return 'replaced';
            const written = write(only.from, only.to, corrected, false);
            if (!written) return 'kept';
            only.to = written.to;
            only.text = written.text;
            return 'replaced';
        },
        discard() {
            if (!alive()) return;
            const removable = segments
                .filter(untouched)
                .sort((a, b) => b.from - a.from);
            if (removable.length === 0) return;
            editor.chain()
                .command(({ tr }) => {
                    tr.setMeta(LIVE_TRANSCRIPT_META, true);
                    for (const segment of removable) {
                        const doc = tr.doc;
                        const size = doc.content.size;
                        const from = segment.spaceBefore && segment.from > 0 &&
                            doc.textBetween(segment.from - 1, segment.from) === ' ' ? segment.from - 1 : segment.from;
                        const to = segment.spaceAfter && segment.to < size &&
                            doc.textBetween(segment.to, segment.to + 1) === ' ' ? segment.to + 1 : segment.to;
                        tr.delete(from, to);
                    }
                    return true;
                })
                .run();
            segments.length = 0;
        },
        destroy() {
            if (destroyed) return;
            if (processing) {
                processing = false;
                refreshProcessing();
            }
            destroyed = true;
            editor.off('transaction', mapSegments);
        },
    };
}
