/**
 * Programmatic renderer for one canonical browser tutorial request.
 *
 * The source recording is copied into a private temporary Remotion public dir,
 * rendered with parameterized props, and removed after the output is complete.
 */

import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import {createHash} from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import {fileURLToPath} from 'node:url';

const [requestPath, outputPath] = process.argv.slice(2);
if (!requestPath || !outputPath) throw new Error('Usage: render.mjs <request.json> <output.mp4>');

const request = JSON.parse(await fs.readFile(requestPath, 'utf8'));
const sha256 = async (filePath) => `sha256:${createHash('sha256').update(await fs.readFile(filePath)).digest('hex')}`;
const expectedSourceHash = request.renderer === 'openmates-remotion-terminal-v1'
	? request.sourceSha256
	: request.sourceHash;
if (await sha256(request.sourceVideo) !== expectedSourceHash) {
	throw new Error('Browser tutorial source hash changed after planning');
}
const compositionId = request.renderer === 'openmates-remotion-terminal-v1'
	? 'OpenMatesTerminalTutorial'
	: 'OpenMatesBrowserTutorial';
const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));
const temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'openmates-proof-remotion-'));
const publicDir = path.join(temporaryRoot, 'public');
await fs.mkdir(publicDir, {recursive: true});
const extension = path.extname(request.sourceVideo) || '.webm';
const sourceName = `source${extension}`;
await fs.copyFile(request.sourceVideo, path.join(publicDir, sourceName));
if (await sha256(path.join(publicDir, sourceName)) !== expectedSourceHash) {
	throw new Error('Browser tutorial copied source hash does not match the plan');
}
const requestSegments = Array.isArray(request.segments) ? request.segments : [];
const segments = await Promise.all(requestSegments.map(async (segment, index) => {
	if (segment.kind !== 'freeze') return segment;
	if (await sha256(segment.source_image) !== segment.source_sha256) {
		throw new Error(`Browser tutorial checkpoint hash changed after planning: ${index}`);
	}
	const imageName = `checkpoint-${index}${path.extname(segment.source_image) || '.png'}`;
	await fs.copyFile(segment.source_image, path.join(publicDir, imageName));
	if (await sha256(path.join(publicDir, imageName)) !== segment.source_sha256) {
		throw new Error(`Browser tutorial copied checkpoint hash does not match the plan: ${index}`);
	}
	return {...segment, source_image: imageName};
}));
const inputProps = request.renderer === 'openmates-remotion-terminal-v1'
	? {...request, sourceVideo: sourceName}
	: {...request, sourceVideo: sourceName, segments};

try {
	const serveUrl = await bundle({
		entryPoint: path.resolve(sourceDirectory, 'index.ts'),
		publicDir,
		rootDir: path.resolve(sourceDirectory, '..')
	});
	const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE || undefined;
	const composition = await selectComposition({
		serveUrl,
		id: compositionId,
		inputProps,
		browserExecutable
	});
	await renderMedia({
		composition,
		serveUrl,
		codec: 'h264',
		outputLocation: outputPath,
		inputProps,
		browserExecutable
	});
} finally {
	await fs.rm(temporaryRoot, {recursive: true, force: true});
}
