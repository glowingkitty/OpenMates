<!--
  2FA reconnect regression preview.
  Renders the real signup one-time-code components in the production issue state:
  2FA is already enabled on the profile, but a reconnect setup is active.
  Used by Playwright to prevent hiding QR/secret actions and the OTP input again.
  This preview has no backend dependency and should stay focused on UI state only.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import OneTimeCodesTopContent from './OneTimeCodesTopContent.svelte';
    import OneTimeCodesBottomContent from './OneTimeCodesBottomContent.svelte';
    import { defaultProfile, userProfile } from '../../../../stores/userProfile';
    import { resetTwoFAData, setTwoFAData } from '../../../../stores/twoFAState';

    const RECONNECT_TEST_SECRET = 'JBSWY3DPEHPK3PXP';
    const RECONNECT_TEST_OTPAUTH_URL =
        'otpauth://totp/OpenMates:reconnect-preview@example.com?secret=JBSWY3DPEHPK3PXP&issuer=OpenMates';

    onMount(() => {
        userProfile.set({
            ...defaultProfile,
            user_id: 'reconnect-preview-user',
            username: 'reconnect-preview',
            last_opened: '#signup/one-time-codes',
            tfa_enabled: true,
            tfa_app_name: null
        });
        setTwoFAData(RECONNECT_TEST_SECRET, '', RECONNECT_TEST_OTPAUTH_URL);

        return () => {
            userProfile.set(defaultProfile);
            resetTwoFAData();
        };
    });
</script>

<section class="preview-shell" data-testid="one-time-codes-reconnect-preview">
    <OneTimeCodesTopContent />
    <OneTimeCodesBottomContent />
</section>

<style>
    .preview-shell {
        width: min(560px, 100%);
        margin: 0 auto;
        padding: var(--spacing-16, 16px);
    }
</style>
