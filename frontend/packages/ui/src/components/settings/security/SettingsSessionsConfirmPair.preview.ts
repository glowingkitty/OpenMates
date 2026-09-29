/** Fictional pending request for the account-free pairing component preview. */
import { pendingPairToken } from "../../../stores/pairSessionStore";
import { userProfile } from "../../../stores/userProfile";
import {
  saveEmailEncryptedWithMasterKey,
  saveEmailSalt,
  saveKeyToSession,
} from "../../../services/cryptoService";

pendingPairToken.set("ABC346");
userProfile.update((profile) => ({
  ...profile,
  user_id: "00000000-0000-4000-8000-000000000001",
}));

// A fictional local account allows the account-free preview to exercise the
// password-plus-email step-up prompt without a real login or account.
export const ready = (async () => {
  const previewMasterKey = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"],
  );
  await saveKeyToSession(previewMasterKey, false);
  await saveEmailEncryptedWithMasterKey("pair-preview@example.test", false);
  saveEmailSalt(new Uint8Array(16).fill(7), false);
})();

export default {};
