import { saveEmailEncryptedWithMasterKey, saveEmailSalt, saveKeyToSession } from '../services/cryptoService';

export const ready = (async () => {
  const masterKey = await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']
  );
  await saveKeyToSession(masterKey, false);
  await saveEmailEncryptedWithMasterKey('device-preview@example.test', false);
  saveEmailSalt(new Uint8Array(16).fill(3), false);
})();

export default {
  reason: 'location_change',
  passwordFallbackAvailable: true,
  passwordCredentialVersion: 2,
};

export const variants = {
  passkey_only: { reason: 'new_device', passwordFallbackAvailable: false },
};
