/**
 * Programmatic renderer for one canonical browser tutorial request.
 *
 * The source recording is copied into a private temporary Remotion public dir,
 * rendered with parameterized props, and removed after the output is complete.
 */

import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import {fileURLToPath} from 'node:url';

const [requestPath, outputPath] = process.argv.slice(2);
if (!requestPath || !outputPath) throw new Error('Usage: render.mjs <request.json> <output.mp4>');

const request = JSON.parse(await fs.readFile(requestPath, 'utf8'));
const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));
const temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'openmates-proof-remotion-'));
const publicDir = path.join(temporaryRoot, 'public');
await fs.mkdir(publicDir, {recursive: true});
const extension = path.extname(request.sourceVideo) || '.webm';
const sourceName = `source${extension}`;
await fs.copyFile(request.sourceVideo, path.join(publicDir, sourceName));
const inputProps = {...request, sourceVideo: sourceName};

try {
	const serveUrl = await bundle({
		entryPoint: path.resolve(sourceDirectory, 'index.ts'),
		publicDir,
		rootDir: path.resolve(sourceDirectory, '..')
	});
	const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE || undefined;
	const composition = await selectComposition({
		serveUrl,
		id: 'OpenMatesBrowserTutorial',
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
