// frontend/packages/ui/src/components/enter_message/services/textLiveTranscript.ts
//
// Live dictation for plain-text composers (textarea based), with the same
// semantics as the canonical editor's `liveTranscriptInsertion`: words stream in
// at the caret, separator spaces keep dictation off neighbouring text, a single
// untouched dictated segment becomes the corrected transcript, text the user
// edited while speaking stays as arranged, and cancelling removes only
// untouched dictated text. Segment offsets follow user edits by diffing each
// observed value against the previous one.

export type TextLiveTranscriptCorrectionOutcome = 'replaced' | 'inserted' | 'kept';

export interface TextComposerAccess {
    /** Current text and selection of the host field. */
    read(): { value: string; selectionStart: number; selectionEnd: number };
    /** Replace the host field's text and place the caret. */
    write(value: string, caret: number): void;
}

export interface TextLiveTranscriptController {
    /** Apply the latest cumulative transcript. Returns true when text was inserted. */
    apply(cumulativeTranscript: string): boolean;
    /** Map dictated ranges through a user edit; call with every new field value. */
    observe(value: string): void;
    hasText(): boolean;
    /** Reconcile the corrected transcript with the dictated text. */
    applyCorrection(correctedTranscript: string): TextLiveTranscriptCorrectionOutcome;
    /** Remove untouched dictated text (used when the recording is cancelled). */
    discard(): void;
}

interface Segment { from: number; to: number; text: string; spaceBefore: boolean; spaceAfter: boolean }

const NO_SPACE_BEFORE = /^[\s.,!?;:)\]}%…]/;
const NO_SPACE_AFTER = /[\s([{]$/;

const normalize = (text: string) => text.replace(/\r\n?/g, '\n');

/** Map an offset from `before` to `after`, given their common prefix/suffix. */
function mapper(before: string, after: string): (offset: number, assoc: -1 | 1) => number {
    let prefix = 0;
    const shortest = Math.min(before.length, after.length);
    while (prefix < shortest && before[prefix] === after[prefix]) prefix++;
    let suffix = 0;
    while (suffix < shortest - prefix && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]) suffix++;
    const changedEnd = before.length - suffix;
    const delta = after.length - before.length;
    return (offset, assoc) => {
        if (offset < prefix || (offset === prefix && assoc < 0 && changedEnd > prefix)) return offset;
        if (offset > changedEnd || (offset === changedEnd && assoc > 0)) return offset + delta;
        // Inside the replaced span: collapse towards its matching side.
        return assoc < 0 ? prefix : changedEnd + delta;
    };
}

export function createTextLiveTranscript(field: TextComposerAccess): TextLiveTranscriptController {
    const segments: Segment[] = [];
    let consumed = '';
    let known = normalize(field.read().value);

    const observe = (value: string) => {
        const next = normalize(value);
        if (next === known) return;
        const map = mapper(known, next);
        for (const segment of segments) {
            segment.from = map(segment.from, 1);
            segment.to = Math.max(segment.from, map(segment.to, -1));
        }
        known = next;
    };

    const untouched = (segment: Segment) => known.slice(segment.from, segment.to) === segment.text;

    const write = (from: number, to: number, text: string, newSegment: boolean): Segment | null => {
        let body = normalize(text);
        let spaceBefore = false;
        let spaceAfter = false;
        if (newSegment) {
            body = body.replace(/^\s+/, '');
            const before = known.slice(Math.max(0, from - 1), from);
            const after = known.slice(to, to + 1);
            spaceBefore = !!before && !NO_SPACE_AFTER.test(before) && !NO_SPACE_BEFORE.test(body);
            spaceAfter = !!after && !NO_SPACE_BEFORE.test(after) && !/\s$/.test(body);
        }
        if (!body) return null;
        const inserted = `${spaceBefore ? ' ' : ''}${body}${spaceAfter ? ' ' : ''}`;
        const bodyFrom = from + (spaceBefore ? 1 : 0);
        const bodyTo = bodyFrom + body.length;
        const value = known.slice(0, from) + inserted + known.slice(to);
        // Our own write shifts later segments exactly like a user edit would.
        const map = mapper(known, value);
        for (const segment of segments) {
            segment.from = map(segment.from, 1);
            segment.to = Math.max(segment.from, map(segment.to, -1));
        }
        known = value;
        field.write(value, bodyTo);
        return { from: bodyFrom, to: bodyTo, text: body, spaceBefore, spaceAfter };
    };

    const selection = () => {
        const current = field.read();
        observe(current.value);
        const from = Math.max(0, Math.min(current.selectionStart, known.length));
        return { from, to: Math.max(from, Math.min(current.selectionEnd, known.length)) };
    };

    return {
        apply(cumulativeTranscript) {
            const transcript = normalize(cumulativeTranscript);
            if (!transcript.startsWith(consumed)) return false;
            const delta = transcript.slice(consumed.length);
            if (!delta) return false;
            const { from, to } = selection();
            const last = segments[segments.length - 1];
            const continues = !!last && from === to && to === last.to && untouched(last);
            const written = write(from, to, delta, !continues);
            consumed = transcript;
            if (!written) return false;
            if (continues) {
                last.to = written.to;
                last.text += written.text;
            } else {
                segments.push(written);
            }
            return true;
        },
        observe,
        hasText() {
            return segments.some((segment) => segment.to > segment.from);
        },
        applyCorrection(correctedTranscript) {
            const corrected = normalize(correctedTranscript).trim();
            if (!corrected) return 'kept';
            if (segments.length === 0) {
                const { from, to } = selection();
                const written = write(from, to, corrected, true);
                if (!written) return 'kept';
                segments.push(written);
                return 'inserted';
            }
            observe(field.read().value);
            const [only] = segments;
            if (segments.length !== 1 || !untouched(only)) return 'kept';
            if (only.text === corrected) return 'replaced';
            const written = write(only.from, only.to, corrected, false);
            if (!written) return 'kept';
            // The write's offset mapping collapses the replaced segment itself; restore its range.
            only.from = written.from;
            only.to = written.to;
            only.text = written.text;
            return 'replaced';
        },
        discard() {
            observe(field.read().value);
            const removable = segments.filter(untouched).sort((a, b) => b.from - a.from);
            if (removable.length === 0) return;
            let value = known;
            let caret = removable[removable.length - 1].from;
            for (const segment of removable) {
                const from = segment.spaceBefore && value[segment.from - 1] === ' ' ? segment.from - 1 : segment.from;
                const to = segment.spaceAfter && value[segment.to] === ' ' ? segment.to + 1 : segment.to;
                value = value.slice(0, from) + value.slice(to);
                caret = from;
            }
            segments.length = 0;
            known = value;
            field.write(value, caret);
        },
    };
}
