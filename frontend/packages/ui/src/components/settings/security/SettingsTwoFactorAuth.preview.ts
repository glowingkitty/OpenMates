/** Fictional unlocked account for isolated 2FA settings previews. */
import {
  saveEmailEncryptedWithMasterKey,
  saveEmailEncryptionKey,
  saveEmailSalt,
  saveKeyToSession,
} from "../../../services/cryptoService";
import { userProfile } from "../../../stores/userProfile";

const enabled =
  new URLSearchParams(window.location.search).get("enabled") === "1";
userProfile.update((profile) => ({
  ...profile,
  tfa_enabled: enabled,
  tfa_app_name: enabled ? "Aegis" : null,
}));

export const ready = (async () => {
  const previewMasterKey = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"],
  );
  await saveKeyToSession(previewMasterKey, false);
  await saveEmailEncryptedWithMasterKey("factor-preview@example.test", false);
  saveEmailSalt(new Uint8Array(16).fill(11), false);
  saveEmailEncryptionKey(new Uint8Array(32).fill(13), false);
})();

export default {};
