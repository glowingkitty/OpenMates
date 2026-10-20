import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({
  get:vi.fn(), decryptImage:vi.fn(), cachedImage:vi.fn(), retainImage:vi.fn(), releaseImage:vi.fn(),
  fetchVideo:vi.fn(), destroyVideo:vi.fn(), epoch:0,
}));
vi.mock('../embedStore', () => ({embedStore:{get:mocks.get}}));
vi.mock('../embedResolver', () => ({decodeToonContent:async (content:string) => JSON.parse(content)}));
vi.mock('../../components/embeds/images/imageEmbedCrypto', () => ({
  fetchAndDecryptImage:mocks.decryptImage, getCachedImageUrl:mocks.cachedImage,
  retainCachedImage:mocks.retainImage, releaseCachedImage:mocks.releaseImage,
}));
vi.mock('../../components/embeds/audio/audioEmbedCrypto', () => ({
  createAudioUrlOwner:() => ({fetch:mocks.fetchVideo,destroy:mocks.destroyVideo}),
}));
vi.mock('../workspaceCacheLifecycle', () => ({getWorkspaceCacheEpoch:() => mocks.epoch}));
import { createVoiceCallMediaResolver } from '../voiceCallMedia';

function leaf(type:'generated_image'|'generated_video', key:string) {
  return {type,content:JSON.stringify({type,status:'finished',s3_base_url:'private',aes_key:'key',aes_nonce:'nonce',files:{original:{s3_key:key,mime_type:type==='generated_image'?'image/png':'video/mp4'}}})};
}
describe('call generated-media ownership', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.epoch = 0;
    mocks.decryptImage.mockResolvedValue(new Blob());
    mocks.cachedImage.mockReturnValue('blob:image');
    mocks.fetchVideo.mockResolvedValue('blob:video');
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('resolves the encrypted generated-media graph once and owns image/video cache references', async () => {
    const graph:Record<string,unknown> = {
      'embed:parent':{app_id:'images',skill_id:'generate',content:JSON.stringify({embed_ids:['image','video','image']})},
      'embed:image':leaf('generated_image','image-key'),
      'embed:video':leaf('generated_video','video-key'),
    };
    mocks.get.mockImplementation(async (id:string) => graph[id]);
    const resolver = createVoiceCallMediaResolver();
    expect(await resolver.resolve(['parent'])).toEqual([
      {embedId:'image',kind:'image',url:'blob:image'}, {embedId:'video',kind:'video',url:'blob:video'},
    ]);
    expect(mocks.retainImage).toHaveBeenCalledOnce();
    expect(mocks.fetchVideo).toHaveBeenCalledWith('private','video-key','key','nonce','video/mp4',expect.objectContaining({s3_key:'video-key'}));
    await resolver.resolve(['image']);
    expect(mocks.retainImage).toHaveBeenCalledOnce();
    resolver.destroy();
    expect(mocks.releaseImage).toHaveBeenCalledWith('image-key');
    expect(mocks.destroyVideo).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('skips undecrypted, processing and unrelated embeds without consuming arbitrary URLs', async () => {
    mocks.get.mockImplementation(async (id:string) => ({
      'embed:pending':{...leaf('generated_image','pending-key'),_decryptionPending:true},
      'embed:processing':{type:'generated_video',content:JSON.stringify({status:'processing',previewVideoUrl:'https://arbitrary.invalid/video.mp4'})},
      'embed:unrelated':{type:'image',content:JSON.stringify({status:'finished',previewImageUrl:'https://arbitrary.invalid/image.png'})},
    })[id]);
    const resolver = createVoiceCallMediaResolver();
    expect(await resolver.resolve(['pending','processing','unrelated'])).toEqual([]);
    expect(mocks.decryptImage).not.toHaveBeenCalled();
    expect(mocks.fetchVideo).not.toHaveBeenCalled();
    resolver.destroy();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('does not retain or publish an image whose decryption completes after hangup', async () => {
    mocks.get.mockResolvedValue(leaf('generated_image','late-key'));
    let finish!: () => void;
    mocks.decryptImage.mockImplementation(() => new Promise<void>(resolve => {finish=resolve;}));
    const resolver = createVoiceCallMediaResolver();
    const pending = resolver.resolve(['image']);
    for(let index=0;index<6;index++) await Promise.resolve();
    resolver.destroy();
    finish();
    expect(await pending).toEqual([]);
    expect(mocks.retainImage).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
  it('fences a result at an account or workspace boundary', async () => {
    mocks.get.mockResolvedValue(leaf('generated_image','private-key'));
    const resolver = createVoiceCallMediaResolver();
    mocks.decryptImage.mockImplementation(async () => {mocks.epoch++;});
    expect(await resolver.resolve(['image'])).toEqual([]);
    expect(mocks.retainImage).not.toHaveBeenCalled();
    resolver.destroy();
  });
});
