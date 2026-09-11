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
const {root, run, encoder} = request;
const requireProject = createRequire(path.join(root, 'package.json'));
const retained = [];
const write = fs.writeFileSync.bind(fs);
const stop = (operation, target) => {
  write(path.join(run, 'stop.json'), JSON.stringify({operation, target: String(target), reason: 'Outside-repository or protected-media mutation requested; no retry permitted'}), {flag: 'wx'});
  process.kill(-process.pid, 'SIGSTOP');
  process.exit(77);
};
const originalRealpath = fs.realpathSync.bind(fs);
function resolved(candidate) {
  let p = path.resolve(String(candidate));
  const suffix = [];
  while (!fs.existsSync(p)) { suffix.unshift(path.basename(p)); const parent = path.dirname(p); if (parent === p) throw new Error('Unresolvable path'); p = parent; }
  return path.join(originalRealpath(p), ...suffix);
}
function requireScope(candidate) {
  const target = resolved(candidate);
  if (!request.roots.some((root) => target !== root && target.startsWith(root + path.sep)) ||
      request.protected.some((root) => target === root || target.startsWith(root + path.sep))) stop('out-of-scope-file-mutation', target);
}
for (const name of ['unlink', 'rm', 'rmdir', 'rename']) {
  for (const [object, key] of [[fs, name], [fs, name + 'Sync'], [fs.promises, name]]) {
    const original = object[key].bind(object);
    object[key] = (...args) => { requireScope(args[0]); if (name === 'rename') requireScope(args[1]); return original(...args); };
  }
}
const originalSpawn = cp.spawn.bind(cp);
cp.spawn = (command, args, options = {}) => {
  const compositor = path.join(path.dirname(encoder), 'remotion');
  const compiler = path.join(root, 'node_modules/@esbuild/darwin-arm64/bin/esbuild');
  if (![compositor, compiler].includes(command)) throw new Error('Unsupported render child: ' + command);
  // Only the compiler transform service and in-process compositor are native
  // children here. Both inherit no-unlink. Browser and encoder are separately
  // launched by Python with no-fork, avoiding unsupported nested sandbox_init.
  const child = originalSpawn(command, args, {...options, detached: false});
  child.on('exit', (code, signal) => {
    if (signal === 'SIGKILL' && !request.finishing) stop('native-child-killed', command);
  });
  return child;
};
async function main() {
  if (requireProject('@remotion/renderer/package.json').version !== '4.0.457') throw new Error('Unaudited renderer version');
  const rendererBase = path.dirname(requireProject.resolve('@remotion/renderer/package.json'));
  if (request.stage === 'bundle') {
    const {bundle} = requireProject('@remotion/bundler');
    const entry = path.join(run, 'check.tsx');
    write(entry, "import React from 'react'; import {AbsoluteFill,Composition,registerRoot} from 'remotion'; const Frame=()=> <AbsoluteFill style={{background:'#101828',color:'white',fontSize:64,justifyContent:'center',alignItems:'center'}}>Retained Mac render check</AbsoluteFill>; registerRoot(()=> <Composition id='RetainedCheck' component={Frame} durationInFrames={1} fps={30} width={1080} height={1920}/>);", {flag: 'wx'});
    const bundlePath = await bundle({entryPoint: entry, outDir: path.join(run, 'bundle'),
      publicDir: path.join(run, 'empty-public'), enableCaching: false,
      webpackOverride: (config) => ({...config, cache: false, output: {...config.output, clean: false}})});
    write(path.join(run, 'result.json'), JSON.stringify({status: 'bundle-ready', bundle: bundlePath, retained}), {flag: 'wx'});
  } else if (request.stage === 'frame') {
    const {HeadlessBrowser} = requireProject(path.join(rendererBase, 'dist/browser/Browser.js'));
    const {Connection} = requireProject(path.join(rendererBase, 'dist/browser/Connection.js'));
    const {NodeWebSocketTransport} = requireProject(path.join(rendererBase, 'dist/browser/NodeWebSocketTransport.js'));
    const transport = await NodeWebSocketTransport.create(request.browserWS);
    const connection = new Connection(transport);
    const runner = {connection, listeners: [], deleteBrowserCaches: () => retained.push(request.profile),
      closeProcess: async () => {}, forgetEventLoop: () => transport.forgetEventLoop(),
      rememberEventLoop: () => transport.rememberEventLoop()};
    const instance = new HeadlessBrowser({connection, runner, defaultViewport: {width: 1080, height: 1920}});
    await connection.send('Target.setDiscoverTargets', {discover: true});
    const {renderStill} = requireProject('@remotion/renderer');
    const output = path.join(run, 'frame-000000.png');
    await renderStill({serveUrl: request.bundlePath, composition: {id: 'RetainedCheck', width: 1080,
      height: 1920, fps: 30, durationInFrames: 1, props: {}, defaultProps: {}},
      puppeteerInstance: instance, output, frame: 0, imageFormat: 'png', logLevel: 'error'});
    write(path.join(run, 'result.json'), JSON.stringify({status: 'frame-ready', frame: output, retained}), {flag: 'wx'});
  } else throw new Error('Unsupported fixed render stage');
  request.finishing = true;
  process.kill(process.pid, 'SIGSTOP');
}
main().catch(async (error) => {
  // Let native exit events surface before freezing an ordinary failure outcome.
  await new Promise((resolve) => setTimeout(resolve, 250));
  write(path.join(run, 'failure.json'), JSON.stringify({error: String(error.stack || error)}), {flag: 'wx'});
  process.kill(process.pid, 'SIGSTOP');
});
