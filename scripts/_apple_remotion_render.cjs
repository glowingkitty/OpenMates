/**
 * Fixed Mac render capability check for TASK-752.
 * Runs only beneath the inherited OS no-unlink sandbox and Python supervisor.
 * Every artifact remains in its exclusive run directory, including profiles.
 * Known Remotion cleanup is replaced by scoped retention before rendering.
 * Unexpected JS removals stop before dispatch; native denials stop in the OS.
 * This is tooling evidence, never a substitute for the marketing composition.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const {createRequire} = require('node:module');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const {root, run, browser, encoder} = request;
const requireProject = createRequire(path.join(root, 'package.json'));
const retained = [];
const write = fs.writeFileSync.bind(fs);
const stop = (operation, target) => {
  write(path.join(run, 'stop.json'), JSON.stringify({operation, target: String(target), reason: 'Unexpected deletion or replacement requested; no retry permitted'}), {flag: 'wx'});
  process.kill(-process.pid, 'SIGSTOP');
  process.exit(77);
};
for (const name of ['unlink', 'rm', 'rmdir', 'rename']) {
  fs[name] = (...args) => stop(name, args[0]);
  fs[name + 'Sync'] = (...args) => stop(name, args[0]);
  fs.promises[name] = (...args) => stop(name, args[0]);
}
const originalSpawn = cp.spawn.bind(cp);
cp.spawn = (command, args, options = {}) => {
  const compositor = path.join(path.dirname(encoder), 'remotion');
  if (![browser, encoder, compositor].includes(command)) throw new Error('Unsupported render child: ' + command);
  // Native helpers cannot create an unobserved grandchild. Fork denial returns
  // an ordinary failure; inherited unlink denial kills the observed child.
  const nativeProfile = '(version 1)(allow default)(deny process-fork)';
  const nativeArgs = command === browser ? [...args, '--single-process', '--in-process-gpu', '--no-zygote', '--disable-crash-reporter'] : args;
  const child = originalSpawn('/usr/bin/sandbox-exec', ['-p', nativeProfile, command, ...nativeArgs], {...options, detached: false});
  child.on('exit', (code, signal) => {
    if (signal === 'SIGKILL' && !request.finishing) stop('native-child-killed', command);
  });
  return child;
};
const retain = (target) => {
  const absolute = path.resolve(target);
  if (!absolute.startsWith(run + path.sep)) stop('cleanup-outside-retained-run', target);
  retained.push(absolute);
};
async function main() {
  if (requireProject('@remotion/renderer/package.json').version !== '4.0.457') throw new Error('Unaudited renderer version');
  const rendererBase = path.dirname(requireProject.resolve('@remotion/renderer/package.json'));
  requireProject(path.join(rendererBase, 'dist/delete-directory.js')).deleteDirectory = retain;
  const maps = requireProject(path.join(rendererBase, 'dist/assets/download-map.js'));
  const makeMap = maps.makeDownloadMap;
  maps.makeDownloadMap = (...args) => {
    const map = makeMap(...args);
    map.preventCleanup();
    retained.push(map.assetDir);
    return map;
  };
  const {bundle} = requireProject('@remotion/bundler');
  const {openBrowser, renderStill} = requireProject('@remotion/renderer');
  const entry = path.join(run, 'check.tsx');
  write(entry, "import React from 'react'; import {AbsoluteFill,Composition,registerRoot} from 'remotion'; const Frame=()=> <AbsoluteFill style={{background:'#101828',color:'white',fontSize:64,justifyContent:'center',alignItems:'center'}}>Retained Mac render check</AbsoluteFill>; registerRoot(()=> <Composition id='RetainedCheck' component={Frame} durationInFrames={1} fps={30} width={1080} height={1920}/>);", {flag: 'wx'});
  const bundlePath = await bundle({entryPoint: entry, outDir: path.join(run, 'bundle'),
    publicDir: path.join(run, 'empty-public'), enableCaching: false,
    webpackOverride: (config) => ({...config, cache: false, output: {...config.output, clean: false}})});
  const instance = await openBrowser('chrome', {browserExecutable: browser, logLevel: 'error'});
  // Passing a browser avoids renderStill owning its profile lifecycle.
  await renderStill({serveUrl: bundlePath, composition: {id: 'RetainedCheck', width: 1080,
    height: 1920, fps: 30, durationInFrames: 1, props: {}, defaultProps: {}},
    puppeteerInstance: instance, output: path.join(run, 'frame-000000.png'),
    frame: 0, imageFormat: 'png', logLevel: 'error'});
  const output = path.join(run, 'check.mp4');
  await new Promise((resolve, reject) => {
    const child = cp.spawn(encoder, ['-n', '-v', 'error', '-loop', '1', '-framerate', '30',
      '-i', path.join(run, 'frame-000000.png'), '-frames:v', '1', '-an', '-c:v', 'libx264',
      '-pix_fmt', 'yuv420p', output], {cwd: path.dirname(encoder), stdio: ['ignore', 'pipe', 'pipe']});
    let errors = '';
    child.stderr.on('data', (chunk) => { errors += chunk; });
    child.on('error', reject);
    child.on('exit', (code) => code === 0 ? resolve() : reject(new Error('Encoder failed: ' + errors)));
  });
  // The supervisor terminates the process group without running native/profile
  // teardown. No browser.close(), temp cleanup, or exit handlers are invoked.
  write(path.join(run, 'result.json'), JSON.stringify({status: 'render-check-passed',
    frame: path.join(run, 'frame-000000.png'), output, retained, bytes: fs.statSync(output).size}), {flag: 'wx'});
  request.finishing = true;
  process.kill(process.pid, 'SIGSTOP');
}
main().catch((error) => {
  write(path.join(run, 'failure.json'), JSON.stringify({error: String(error.stack || error)}), {flag: 'wx'});
  process.kill(process.pid, 'SIGSTOP');
});
