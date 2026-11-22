// proof-video: not_required reason=non_visual_setup (tests the proof-audio recorder itself; its muxed video is the artifact)
// playwright-account: not_required reason=isolated_component_preview
/**
 * Proof videos carry the page's audio in sync (tests/helpers/proof-audio.ts, owner 22 Nov 2026).
 *
 * A routed test page plays, at recorded moments: a Web Audio beep, an <audio> element, a muted
 * <audio> element (must stay silent) and the fake microphone (the test voice). After the test,
 * the muxed `video-with-audio.webm` must be loud exactly at those moments and silent before the
 * beep and during the muted clip, which proves the capture and the sync (window of ±0.2 s).
 * No backend, account or provider is involved.
 */
import type { TestInfo } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

/* eslint-disable @typescript-eslint/no-require-imports -- helpers export CommonJS-compatible values. */
const { test: baseTest, expect } = require('../helpers/cookie-audit');
const { withProofAudio, proofAudioLaunchArgs } = require('../helpers/proof-audio');

const test = withProofAudio(baseTest);
test.use({ launchOptions: { args: proofAudioLaunchArgs({ autoplay: true }) }, video: 'on' });

const ORIGIN = 'https://proof-audio.test';
const LOUDNESS = path.resolve(__dirname, '../../../../../scripts/proof_video_audio.py');

/** A mono 16-bit PCM WAV with a sine tone. */
function toneWav(frequency: number, seconds: number, rate = 48_000): Buffer {
  const samples = Math.round(seconds * rate);
  const wav = Buffer.alloc(44 + samples * 2);
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + samples * 2, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++) wav.writeInt16LE(Math.round(Math.sin(2 * Math.PI * frequency * i / rate) * 12_000), 44 + i * 2);
  return wav;
}

const moments: Record<string, number> = {};
let outputDir = '';

// contract-test: tooling
test('page audio, element audio and the fake microphone are recorded; muted audio is not', async ({ page }: { page: any }, testInfo: TestInfo) => {
  outputDir = testInfo.outputDir;
  const tone = toneWav(660, 0.6);
  await page.route(`${ORIGIN}/**`, (route: any) => route.request().url().endsWith('/tone.wav')
    ? route.fulfill({ status: 200, contentType: 'audio/wav', body: tone })
    : route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Proof audio</title><h1>Proof audio</h1>' }));
  await page.goto(`${ORIGIN}/`);
  await page.waitForTimeout(1_500);

  moments.beep = await page.evaluate(() => {
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    gain.gain.value = 0.4;
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.5);
    return Date.now();
  });
  await page.waitForTimeout(1_500);

  moments.element = await page.evaluate(async (url: string) => {
    const audio = new Audio(url);
    await audio.play();
    return Date.now();
  }, `${ORIGIN}/tone.wav`);
  await page.waitForTimeout(1_500);

  moments.muted = await page.evaluate(async (url: string) => {
    const audio = new Audio(url);
    audio.muted = true;
    await audio.play();
    return Date.now();
  }, `${ORIGIN}/tone.wav`);
  await page.waitForTimeout(1_500);

  moments.microphone = await page.evaluate(async () => {
    (window as any).proofMicrophone = await navigator.mediaDevices.getUserMedia({ audio: true });
    return Date.now();
  });
  await page.waitForTimeout(3_000);
  await expect(page.getByRole('heading', { name: 'Proof audio' })).toBeVisible();
});

test.afterAll(() => {
  const dir = path.join(outputDir, 'proof-audio');
  const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'proof-audio-manifest.json'), 'utf8'));
  const [first] = manifest.pages;
  expect(first.errors, 'recorder errors').toEqual([]);
  // The beep's AudioContext, both <audio> elements (the muted one silenced) and the microphone.
  expect(first.audio_sources, 'tapped audio sources').toBe(4);
  const muxed = path.join(dir, 'video-0-with-audio.webm');
  expect(fs.existsSync(muxed), 'muxed proof video').toBe(true);
  const at = (name: string) => (moments[name] - first.created_epoch_ms) / 1000;
  const loudness = (start: number, duration: number) => {
    const run = spawnSync('python3', [LOUDNESS, 'loudness', muxed, '--start', String(Math.max(0, start)),
      '--duration', String(duration)], { encoding: 'utf8' });
    expect(run.status, run.stderr).toBe(0);
    return Number(run.stdout.trim());
  };
  expect(loudness(at('beep') - 1.0, 0.8), 'silence before the beep').toBeLessThan(-50);
  expect(loudness(at('beep') + 0.05, 0.3), 'Web Audio beep').toBeGreaterThan(-30);
  expect(loudness(at('element') + 0.1, 0.3), '<audio> element').toBeGreaterThan(-30);
  expect(loudness(at('muted') + 0.15, 0.35), 'muted <audio> element stays silent').toBeLessThan(-50);
  expect(loudness(at('microphone') + 0.5, 2.0), 'fake microphone test voice').toBeGreaterThan(-40);
});
