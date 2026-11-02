// frontend/packages/ui/src/components/enter_message/extensions/RecordingTranscriptProcessing.ts
//
// Marks live-dictated transcript ranges with an animated gradient while the
// recording's correction pass is running. Ranges are supplied by MessageInput
// through a transaction meta and are mapped through later document changes, so
// typing elsewhere never shifts the shimmer onto unrelated text.

import { Extension } from '@tiptap/core';
import { Plugin, PluginKey, type EditorState, type Transaction } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';

export interface TranscriptRange { from: number; to: number }

export const recordingTranscriptProcessingKey = new PluginKey<DecorationSet>('recordingTranscriptProcessing');

export const RECORDING_TRANSCRIPT_PROCESSING_CLASS = 'recording-transcript-processing';

function buildDecorations(state: EditorState, ranges: TranscriptRange[]): DecorationSet {
    const size = state.doc.content.size;
    const decorations = ranges
        .map(({ from, to }) => ({ from: Math.max(0, Math.min(from, size)), to: Math.max(0, Math.min(to, size)) }))
        .filter(({ from, to }) => to > from)
        .map(({ from, to }) => Decoration.inline(from, to, {
            class: RECORDING_TRANSCRIPT_PROCESSING_CLASS,
            'data-testid': 'recording-transcript-processing',
        }));
    return DecorationSet.create(state.doc, decorations);
}

/** Replace the highlighted ranges; pass an empty list to clear them. */
export function setRecordingTranscriptProcessing(tr: Transaction, ranges: TranscriptRange[]): Transaction {
    return tr.setMeta(recordingTranscriptProcessingKey, ranges);
}

export const RecordingTranscriptProcessing = Extension.create({
    name: 'recordingTranscriptProcessing',
    addProseMirrorPlugins() {
        return [
            new Plugin<DecorationSet>({
                key: recordingTranscriptProcessingKey,
                state: {
                    init: () => DecorationSet.empty,
                    apply(tr, previous, _oldState, newState) {
                        const ranges = tr.getMeta(recordingTranscriptProcessingKey) as TranscriptRange[] | undefined;
                        if (ranges) return buildDecorations(newState, ranges);
                        return tr.docChanged ? previous.map(tr.mapping, tr.doc) : previous;
                    },
                },
                props: {
                    decorations(state) {
                        return recordingTranscriptProcessingKey.getState(state);
                    },
                },
            }),
        ];
    },
});
