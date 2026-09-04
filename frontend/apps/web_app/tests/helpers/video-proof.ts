/**
 * Spec-owned proof-video contract and event timeline runtime.
 *
 * Playwright specs declare complete tutorial text and visible assertions here,
 * while actions and checkpoints only record timestamps. Presentation pacing is
 * performed after the fast source test and never adds sleeps to test execution.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const {createHash} = require('node:crypto');

type ProofDevice = 'web-laptop' | 'web-phone' | 'cli-terminal';

interface ProofTranscriptCue {
	id: string;
	text: string;
	checkpoint: string;
	devices: ProofDevice[];
}

interface ProofAssertion {
	id: string;
	checkpoint: string;
	visual: string;
	devices: ProofDevice[];
}

interface VideoProofDefinition {
	id: string;
	title: string;
	surface: 'web' | 'cli';
	devices: ProofDevice[];
	domain?: string;
	transcript: ProofTranscriptCue[];
	assertions: ProofAssertion[];
	tutorial: {
		readingWordsPerSecond: number;
		minimumHoldMs: number;
		maximumHoldMs: number;
	};
}

interface RuntimeOptions {
	now?: () => number;
	device: ProofDevice;
	attach: (name: string, options: {body: Buffer; contentType: string}) => Promise<void>;
	captureFrame?: () => Promise<Buffer>;
}

function requireText(value: unknown, label: string): asserts value is string {
	if (typeof value !== 'string' || !value.trim()) throw new Error(`Video proof ${label} must be non-empty`);
}

function requireDevices(devices: unknown, allowed: ProofDevice[], label: string): asserts devices is ProofDevice[] {
	if (!Array.isArray(devices) || devices.length === 0 || devices.some((device) => !allowed.includes(device))) {
		throw new Error(`Video proof ${label} devices must be declared contract devices`);
	}
}

function defineVideoProof(input: VideoProofDefinition): VideoProofDefinition {
	const value = structuredClone(input);
	requireText(value.id, 'id');
	requireText(value.title, 'title');
	if (!['web', 'cli'].includes(value.surface)) throw new Error('Video proof surface must be web or cli');
	if (!Array.isArray(value.devices) || value.devices.length === 0 || new Set(value.devices).size !== value.devices.length) {
		throw new Error('Video proof devices must be a unique non-empty list');
	}
	if (value.surface === 'web') requireText(value.domain, 'domain');
	if (!Array.isArray(value.transcript) || value.transcript.length === 0) throw new Error('Video proof transcript is required');
	if (!Array.isArray(value.assertions) || value.assertions.length === 0) throw new Error('Video proof assertions are required');

	const cueIds = new Set<string>();
	for (const cue of value.transcript) {
		requireText(cue.id, 'transcript id');
		requireText(cue.text, 'transcript text');
		requireText(cue.checkpoint, 'transcript checkpoint');
		requireDevices(cue.devices, value.devices, `transcript ${cue.id}`);
		if (cueIds.has(cue.id)) throw new Error(`Duplicate video proof transcript id ${cue.id}`);
		cueIds.add(cue.id);
	}

	const assertionIds = new Set<string>();
	for (const assertion of value.assertions) {
		requireText(assertion.id, 'assertion id');
		requireText(assertion.checkpoint, `assertion ${assertion.id} checkpoint`);
		requireText(assertion.visual, `assertion ${assertion.id} visual review text`);
		requireDevices(assertion.devices, value.devices, `assertion ${assertion.id}`);
		if (assertionIds.has(assertion.id)) throw new Error(`Duplicate video proof assertion id ${assertion.id}`);
		assertionIds.add(assertion.id);
	}

	const policy = value.tutorial;
	if (!(policy.readingWordsPerSecond > 0)) throw new Error('Video proof readingWordsPerSecond must be positive');
	if (!(policy.minimumHoldMs > 0 && policy.maximumHoldMs >= policy.minimumHoldMs)) {
		throw new Error('Video proof hold bounds are invalid');
	}
	return value;
}

function createVideoProofRuntime(definition: VideoProofDefinition, options: RuntimeOptions) {
	const contract = defineVideoProof(definition);
	if (!contract.devices.includes(options.device)) throw new Error(`Video proof device ${options.device} is not declared`);
	const now = options.now ?? Date.now;
	const startedAt = now();
	const events: Array<Record<string, unknown>> = [];
	const assertionResults: Array<Record<string, unknown>> = [];
	const reachedCheckpoints = new Set<string>();
	const executedAssertions = new Set<string>();
	const checkpointFrames: Array<Record<string, unknown>> = [];
	return {
		async action<T>(id: string, callback: () => Promise<T>): Promise<T> {
			requireText(id, 'action id');
			const startAtEpochMs = now();
			const result = await callback();
			const endAtEpochMs = now();
			events.push({
				id,
				kind: 'action',
				start_ms: startAtEpochMs - startedAt,
				end_ms: endAtEpochMs - startedAt,
				start_at_epoch_ms: startAtEpochMs,
				end_at_epoch_ms: endAtEpochMs
			});
			return result;
		},
		async assert<T>(id: string, callback: () => Promise<T>): Promise<T> {
			const declared = contract.assertions.find((assertion) => assertion.id === id && assertion.devices.includes(options.device));
			if (!declared) throw new Error(`Video proof assertion ${id} is not declared for ${options.device}`);
			const at = now() - startedAt;
			try {
				const result = await callback();
				const capturedAtEpochMs = now();
				executedAssertions.add(id);
				assertionResults.push({id, status: 'passed', at_ms: capturedAtEpochMs - startedAt, captured_at_epoch_ms: capturedAtEpochMs});
				events.push({id, kind: 'assertion', at_ms: capturedAtEpochMs - startedAt, captured_at_epoch_ms: capturedAtEpochMs, status: 'passed'});
				return result;
			} catch (error) {
				const capturedAtEpochMs = now();
				assertionResults.push({id, status: 'failed', at_ms: capturedAtEpochMs - startedAt, captured_at_epoch_ms: capturedAtEpochMs});
				events.push({id, kind: 'assertion', at_ms: at, captured_at_epoch_ms: capturedAtEpochMs, status: 'failed'});
				throw error;
			}
		},
		async checkpoint(id: string): Promise<void> {
			requireText(id, 'checkpoint id');
			const capturedAtEpochMs = now();
			const atMs = capturedAtEpochMs - startedAt;
			if (contract.surface === 'web') {
				const frame: Record<string, unknown> = {checkpoint: id, at_ms: atMs, captured_at_epoch_ms: capturedAtEpochMs};
				if (options.captureFrame) {
					const body = await options.captureFrame();
					const attachmentName = `openmates-proof-frame-${id}`;
					await options.attach(attachmentName, {body, contentType: 'image/png'});
					frame.attachment_name = attachmentName;
					frame.sha256 = `sha256:${createHash('sha256').update(body).digest('hex')}`;
				}
				checkpointFrames.push(frame);
			} else if (options.captureFrame) {
				const body = await options.captureFrame();
				const attachmentName = `openmates-proof-frame-${id}`;
				await options.attach(attachmentName, {body, contentType: 'image/png'});
				checkpointFrames.push({
					checkpoint: id,
					attachment_name: attachmentName,
					sha256: `sha256:${createHash('sha256').update(body).digest('hex')}`
				});
			}
			reachedCheckpoints.add(id);
			events.push({id, kind: 'checkpoint', at_ms: atMs, captured_at_epoch_ms: capturedAtEpochMs});
		},
		async attach(): Promise<void> {
			for (const assertion of contract.assertions.filter((item) => item.devices.includes(options.device))) {
				if (!executedAssertions.has(assertion.id)) throw new Error(`Video proof assertion ${assertion.id} was not executed`);
				if (!reachedCheckpoints.has(assertion.checkpoint)) throw new Error(`Video proof checkpoint ${assertion.checkpoint} was not reached`);
			}
			for (const cue of contract.transcript.filter((item) => item.devices.includes(options.device))) {
				if (!reachedCheckpoints.has(cue.checkpoint)) throw new Error(`Video proof checkpoint ${cue.checkpoint} was not reached`);
			}
			const payload = {
				schema_version: contract.surface === 'web' ? 2 : 1,
				device: options.device,
				contract,
				events,
				assertion_results: assertionResults,
				checkpoint_frames: checkpointFrames
			};
			await options.attach('openmates-proof-timeline', {
				body: Buffer.from(JSON.stringify(payload)),
				contentType: 'application/vnd.openmates.proof-timeline+json'
			});
		}
	};
}

module.exports = {createVideoProofRuntime, defineVideoProof};
