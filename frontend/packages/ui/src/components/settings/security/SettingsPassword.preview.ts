/** Fictional unlocked account for the account-free password settings preview. */
import {
  saveEmailEncryptedWithMasterKey,
  saveEmailSalt,
  saveKeyToSession,
} from "../../../services/cryptoService";

export const ready = (async () => {
  const previewMasterKey = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"],
  );
  await saveKeyToSession(previewMasterKey, false);
  await saveEmailEncryptedWithMasterKey("password-preview@example.test", false);
  saveEmailSalt(new Uint8Array(16).fill(9), false);
})();

export default {};
