// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import * as uploadPrivacy from '@repo/upload-privacy';
import { prepareFileForUpload } from '../uploadPrivacy';
import { VoiceCallCamera } from '../voiceCallCamera';

// A real, decodable JPEG with the APP0/JFIF header also emitted by browser canvas.
const jfifJpeg = readFileSync('static/images/examples/group1.jpg');
const jfifDataUrl = `data:image/jpeg;base64,${jfifJpeg.toString('base64')}`;
function mockCanvas() {
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockReturnValue(4);
  vi.spyOn(HTMLVideoElement.prototype, 'videoWidth', 'get').mockReturnValue(2160);
  vi.spyOn(HTMLVideoElement.prototype, 'videoHeight', 'get').mockReturnValue(3840);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D);
  return vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(jfifDataUrl);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function cameraStream() {
  const track = { stop: vi.fn(), onended: null as (() => void) | null };
  return { stream: { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream, track };
}
const flush = async () => { for (let index = 0; index < 6; index++) await Promise.resolve(); };

describe('live call camera', () => {
  let getUserMedia: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    vi.useFakeTimers();
    getUserMedia = vi.fn();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output,video-call.audio.single-owner
  it('releases late permission grants after stop and never publishes their stream', async () => {
    const pending = deferred<MediaStream>();
    getUserMedia.mockReturnValue(pending.promise);
    const callbacks = { onFrame:vi.fn(), onStream:vi.fn(), onError:vi.fn() };
    const camera = new VoiceCallCamera(callbacks);
    const start = camera.start();
    camera.stop();
    const { stream, track } = cameraStream();
    pending.resolve(stream);
    await start;
    expect(track.stop).toHaveBeenCalledOnce();
    expect(callbacks.onStream.mock.calls.every(([stream]) => stream === null)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(callbacks.onError).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('uses rear video-only capture, stops the old track on flip and stops the replacement on hangup', async () => {
    const rear = cameraStream();
    const front = cameraStream();
    getUserMedia.mockResolvedValueOnce(rear.stream).mockResolvedValueOnce(front.stream);
    const callbacks = { onFrame:vi.fn(), onStream:vi.fn(), onError:vi.fn() };
    const camera = new VoiceCallCamera(callbacks);
    await camera.start();
    expect(getUserMedia).toHaveBeenNthCalledWith(1, expect.objectContaining({ audio:false, video:expect.objectContaining({facingMode:{ideal:'environment'}}) }));
    await camera.flip();
    expect(rear.track.stop).toHaveBeenCalledOnce();
    expect(getUserMedia).toHaveBeenNthCalledWith(2, expect.objectContaining({ audio:false, video:expect.objectContaining({facingMode:{ideal:'user'}}) }));
    expect(camera.facing).toBe('user');
    camera.stop();
    expect(front.track.stop).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('sends at most one bounded portrait JPEG per second and no frames after stop', async () => {
    getUserMedia.mockResolvedValue(cameraStream().stream);
    const encode = mockCanvas();
    const sanitized = await uploadPrivacy.sanitizeUploadBytes(jfifJpeg,'image/jpeg','camera-frame.jpg');
    const callbacks = { onFrame:vi.fn(), onStream:vi.fn(), onError:vi.fn() };
    const camera = new VoiceCallCamera(callbacks);
    await camera.start();
    await vi.advanceTimersByTimeAsync(999);
    expect(callbacks.onFrame).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(callbacks.onFrame).toHaveBeenCalledOnce();
    expect(callbacks.onFrame).toHaveBeenLastCalledWith(expect.objectContaining({width:405,height:720}));
    expect(Uint8Array.from(atob(callbacks.onFrame.mock.calls[0][0].data), character => character.charCodeAt(0))).toEqual(sanitized.bytes);
    await vi.advanceTimersByTimeAsync(2000);
    expect(callbacks.onFrame).toHaveBeenCalledTimes(3);
    encode.mockReturnValue(`data:image/jpeg;base64,${'A'.repeat(360000)}`);
    await vi.advanceTimersByTimeAsync(1000);
    expect(callbacks.onFrame).toHaveBeenCalledTimes(3);
    camera.stop();
    await vi.advanceTimersByTimeAsync(3000);
    expect(callbacks.onFrame).toHaveBeenCalledTimes(3);
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output,video-call.video.source-frame-provenance
  it('emits JFIF JPEG bytes identical to an ordinary prepared upload and idempotent second sanitation', async () => {
    expect(jfifJpeg.subarray(2,11)).toEqual(Buffer.from([255,224,0,16,74,70,73,70,0]));
    getUserMedia.mockResolvedValue(cameraStream().stream);
    mockCanvas();
    const callbacks = {onFrame:vi.fn(),onStream:vi.fn(),onError:vi.fn()};
    const camera = new VoiceCallCamera(callbacks);
    await camera.start();
    await vi.advanceTimersByTimeAsync(1000);
    expect(callbacks.onFrame).toHaveBeenCalledOnce();
    const frame = callbacks.onFrame.mock.calls[0][0];
    const wireBytes = Uint8Array.from(atob(frame.data), character => character.charCodeAt(0));
    camera.stop();
    vi.useRealTimers();
    const expected = await uploadPrivacy.sanitizeUploadBytes(jfifJpeg,'image/jpeg','camera-frame.jpg');
    expect(expected.status).toBe('sanitized');
    expect(wireBytes).toEqual(expected.bytes);
    expect(wireBytes.byteLength).toBeLessThan(jfifJpeg.byteLength);
    const uploaded = await prepareFileForUpload(new File([wireBytes],'camera-frame.jpg',{type:'image/jpeg'}));
    expect(new Uint8Array(await uploaded.arrayBuffer())).toEqual(wireBytes);
    const second = await uploadPrivacy.sanitizeUploadBytes(wireBytes,'image/jpeg','camera-frame.jpg');
    expect(second.status).toBe('sanitized');
    expect(second.bytes).toEqual(wireBytes);
    expect(callbacks.onError).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output,video-call.video.source-frame-provenance
  it('fences pending sanitation after stop and does not queue additional captures', async () => {
    getUserMedia.mockResolvedValue(cameraStream().stream);
    const encode = mockCanvas();
    const cleaned = await uploadPrivacy.sanitizeUploadBytes(jfifJpeg,'image/jpeg','camera-frame.jpg');
    const pending = deferred<typeof cleaned>();
    const sanitize = vi.spyOn(uploadPrivacy,'sanitizeUploadBytes').mockReturnValueOnce(pending.promise);
    const callbacks = {onFrame:vi.fn(),onStream:vi.fn(),onError:vi.fn()};
    const camera = new VoiceCallCamera(callbacks);
    await camera.start();
    await vi.advanceTimersByTimeAsync(3000);
    expect(encode).toHaveBeenCalledOnce();
    expect(sanitize).toHaveBeenCalledOnce();
    camera.stop();
    pending.resolve(cleaned);
    await flush();
    expect(callbacks.onFrame).not.toHaveBeenCalled();
    expect(callbacks.onError).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('preserves the one-Hz emission bound when sanitation completes between capture ticks', async () => {
    getUserMedia.mockResolvedValue(cameraStream().stream);
    mockCanvas();
    const cleaned = await uploadPrivacy.sanitizeUploadBytes(jfifJpeg,'image/jpeg','camera-frame.jpg');
    const pending = deferred<typeof cleaned>();
    vi.spyOn(uploadPrivacy,'sanitizeUploadBytes').mockReturnValueOnce(pending.promise);
    const callbacks = {onFrame:vi.fn(),onStream:vi.fn(),onError:vi.fn()};
    const camera = new VoiceCallCamera(callbacks);
    await camera.start();
    await vi.advanceTimersByTimeAsync(1900);
    pending.resolve(cleaned);
    await flush();
    expect(callbacks.onFrame).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(100);
    expect(callbacks.onFrame).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1000);
    expect(callbacks.onFrame).toHaveBeenCalledTimes(2);
    camera.stop();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('reports permission denial without a stream and ignores an obsolete permission rejection', async () => {
    const callbacks = { onFrame:vi.fn(), onStream:vi.fn(), onError:vi.fn() };
    const camera = new VoiceCallCamera(callbacks);
    getUserMedia.mockRejectedValueOnce(new DOMException('Denied', 'NotAllowedError'));
    await camera.start();
    expect(callbacks.onError).toHaveBeenCalledWith('camera_denied');
    callbacks.onError.mockClear();
    const pending = deferred<MediaStream>();
    getUserMedia.mockReturnValueOnce(pending.promise);
    const start = camera.start();
    camera.stop();
    pending.reject(new DOMException('Denied', 'NotAllowedError'));
    await start;
    await flush();
    expect(callbacks.onError).not.toHaveBeenCalled();
  });
});
