import { derivePasswordV2Direct } from './passwordV2Core';

self.onmessage = async (event: MessageEvent<{ password: string; userEmailSalt: Uint8Array }>) => {
    try {
        const keys = await derivePasswordV2Direct(event.data.password, event.data.userEmailSalt);
        self.postMessage(keys, { transfer: [keys.authKey.buffer, keys.wrapKey.buffer] });
    } catch {
        self.postMessage({ error: 'Password derivation failed' });
    }
};
