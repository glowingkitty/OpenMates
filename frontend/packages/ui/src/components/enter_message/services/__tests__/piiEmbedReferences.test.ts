// Embed references are never altered by personal-data detection/redaction:
// a ref built from a local UUID can look like a phone number, and a redacted
// ref can never resolve to its upload again ("Preview unavailable").
import { describe, expect, it } from 'vitest';
import { detectPII, replacePIIWithPlaceholders } from '../piiDetectionService';
import { mergeWebPIIMatches } from '../webPIIMatches';
import { ProjectFilePrivacy } from '../../../../services/projectFilePrivacy';

// Same shape as the CLI's `createEmbedRef("<file>:<uuid>")`; the digit run
// inside the UUID part matches the local phone-number pattern on its own.
const ref = 'x-81ede84d-0123-4567-91b3--2e1a33';
const phone = '+49 2123 21234';
const link = `[!](embed:${ref})`;
const jsonBlock = '```json\n' + JSON.stringify({ type: 'image', embed_id: ref }) + '\n```';

describe('embed references and personal-data detection', () => {
	// contract-test: supporting surface=gui.web assertions=pii.composer.embed-references-not-scanned
	it('the bare ref text is phone-like, so the protection below is load-bearing', () => {
		expect(detectPII(`see ${ref} here`).some((m) => m.type === 'PHONE')).toBe(true);
		// cli-file-upload.spec.ts uploads `whiteboard-0301-2345-678.png`; its ref is
		// phone-like whatever the random embed id is.
		const e2eRef = 'whiteboard-0301-2345-678-png-81ede84d-01-2e1a33';
		expect(detectPII(`see ${e2eRef} here`).some((m) => m.type === 'PHONE')).toBe(true);
		expect(detectPII(`see [!](embed:${e2eRef}) here`)).toEqual([]);
	});

	// contract-test: supporting surface=gui.web assertions=pii.composer.embed-references-not-scanned
	it('leaves a markdown embed link unchanged and still redacts a phone number elsewhere', () => {
		const text = `Look at this ${link}\ncall ${phone} now`;
		const matches = detectPII(text);
		const redacted = replacePIIWithPlaceholders(text, matches);
		expect(redacted).toContain(link);
		expect(redacted).not.toContain(phone);
		expect(matches.map((m) => m.match)).toEqual([phone]);
	});

	// contract-test: supporting surface=gui.web assertions=pii.composer.embed-references-not-scanned
	it('leaves a json embed reference block unchanged and still redacts a phone number elsewhere', () => {
		const text = `${jsonBlock}\ncall ${phone} now`;
		const redacted = replacePIIWithPlaceholders(text, detectPII(text));
		expect(redacted).toContain(jsonBlock);
		expect(redacted).not.toContain(phone);
	});

	// contract-test: supporting surface=gui.web assertions=pii.composer.embed-references-not-scanned
	it('still scans the display text of an embed link and ordinary json code blocks', () => {
		const display = `[call ${phone}](embed:${ref})`;
		expect(replacePIIWithPlaceholders(display, detectPII(display))).toContain(`](embed:${ref})`);
		expect(detectPII(display).map((m) => m.match)).toEqual([phone]);
		const code = '```json\n' + JSON.stringify({ note: `call ${phone}` }) + '\n```';
		expect(detectPII(code).map((m) => m.match)).toEqual([phone]);
		// A user note next to the ids of an embed reference block is human text.
		const noted = '```json\n' + JSON.stringify({ embed_id: ref, embed_ids: [ref], note: `call ${phone}` }) + '\n```';
		const redacted = replacePIIWithPlaceholders(noted, detectPII(noted));
		expect(redacted).toContain(`"embed_id":"${ref}","embed_ids":["${ref}"]`);
		expect(redacted).not.toContain(phone);
	});

	// contract-test: supporting surface=gui.web assertions=pii.composer.embed-references-not-scanned
	it('personal data entries never cut into an embed ref', () => {
		const options = { personalDataEntries: [{ id: 'p', textToHide: '81ede84d', replaceWith: 'SECRET_CODE' }] };
		const text = `${link} and 81ede84d`;
		const matches = detectPII(text, options);
		expect(replacePIIWithPlaceholders(text, matches)).toBe(`${link} and [SECRET_CODE]`);
	});

	// contract-test: supporting surface=gui.web assertions=pii.composer.embed-references-not-scanned
	it('model spans overlapping an embed ref are dropped by the merge', () => {
		const text = `${link} from Alice`;
		const start = text.indexOf('0123');
		const entities = [
			{ label: 'PHONE', original: text.slice(start, start + 12), start, end: start + 12, confidence: 1 },
			{ label: 'GIVEN_NAME', original: 'Alice', start: text.indexOf('Alice'), end: text.indexOf('Alice') + 5, confidence: 1 },
		];
		const merged = mergeWebPIIMatches(text, entities);
		expect(merged.some((m) => m.startIndex < link.length)).toBe(false);
		expect(replacePIIWithPlaceholders(text, merged)).toContain(link);
	});

	// contract-test: supporting surface=gui.web assertions=pii.composer.embed-references-not-scanned
	it('CLI message redaction keeps the appended reference block intact', () => {
		const privacy = new ProjectFilePrivacy({ save: async () => {}, mappings: [{ placeholder: '[OM_PII_0123]', original: '4567', type: 'OTHER' }] });
		const message = `Please look at the file, call ${phone}\n\n${link}`;
		const start = message.indexOf('0123');
		const redacted = privacy.redactText(message, [{ start, end: start + 9, type: 'PHONE' }]);
		expect(redacted.endsWith(link)).toBe(true);
		expect(redacted).not.toContain(phone);
	});
});
