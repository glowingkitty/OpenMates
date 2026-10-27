import { describe, expect, it, vi } from 'vitest';
vi.mock('../../components/enter_message/services/uploadService', () => ({ uploadFileToServer: vi.fn(async () => ({ embed_id: 'uploaded', files: { original: { s3_key: 'audio-key' } }, s3_base_url: 'https://s3.test', aes_key: 'exact-aes', aes_nonce: 'exact-nonce', vault_wrapped_aes_key: 'exact-wrapped' })) }));
import { appsImageDimensions, prepareAppsRequestAttachments } from '../appsWorkspaceAttachmentService';
import { uploadFileToServer } from '../../components/enter_message/services/uploadService';
describe('Apps supported attachment preparation', () => {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('fits the entire image inside bounded decision dimensions with padding for thin images', () => {
    expect(appsImageDimensions(4000, 2000)).toEqual({ width: 1568, height: 784, imageWidth: 1568, imageHeight: 784 });
    expect(appsImageDimensions(10, 1000)).toEqual({ width: 280, height: 1000, imageWidth: 10, imageHeight: 1000 });
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('passes exact existing encrypted upload metadata as the audio request without model-generated keys', async () => {
    const file = new File(['sound'], 'voice.webm', { type: 'audio/webm' });
    const assertCurrent = vi.fn();
    const result = await prepareAppsRequestAttachments([file], { chatId: 'source', assertCurrent });
    expect(uploadFileToServer).toHaveBeenCalledWith(file, undefined);
    expect(result.attachments[0].input).toMatchObject({ embed_id: 'uploaded', s3_key: 'audio-key', s3_base_url: 'https://s3.test', aes_key: 'exact-aes', aes_nonce: 'exact-nonce', vault_wrapped_aes_key: 'exact-wrapped', filename: 'voice.webm', mime_type: 'audio/webm', chat_id: 'source' });
    expect(assertCurrent).toHaveBeenCalledTimes(2);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('stops before uploading when the owner changed', async () => {
    const file = new File(['sound'], 'voice.webm', { type: 'audio/webm' });
    await expect(prepareAppsRequestAttachments([file], { assertCurrent: () => { throw new Error('account_context_changed'); } })).rejects.toThrow('account_context_changed');
  });
});
