// Ordinary Node Worker creation: no syscall forcing or environment workaround.
import { Worker, isMainThread, parentPort } from 'node:worker_threads';
if (isMainThread) {
  const workers = [new Worker(new URL(import.meta.url)), new Worker(new URL(import.meta.url))];
  await Promise.all(workers.map(worker => new Promise((resolve, reject) => {
    worker.once('message', () => worker.postMessage('release'));
    worker.once('error', reject);
    worker.once('exit', code => code === 0 ? resolve() : reject(new Error('worker exit')));
  })));
  console.log(JSON.stringify({ fixture: 'node-threads', unit: 'KiB',
    rootThreadGroupPeakRssKiB: process.resourceUsage().maxRSS,
    wholeFixturePeakRssKiB: process.resourceUsage().maxRSS,
    rssScope: 'one-known-thread-group', acceptanceEligible: false }));
} else {
  const allocation = Buffer.alloc(8 * 1024 * 1024, 17);
  parentPort.once('message', () => { if (allocation[0] !== 17) throw new Error('allocation'); });
  parentPort.postMessage('ready');
}
