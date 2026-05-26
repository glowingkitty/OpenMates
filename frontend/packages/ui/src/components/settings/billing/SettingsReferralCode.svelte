<!--
Referral Code Settings - Shows the user's stable referral link and conditions
for promotional referral credits.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import QRCodeSVG from 'qrcode-svg';
    import { loadReferralStatus, referralStatus } from '../../../services/referralService';
    import { notificationStore } from '../../../stores/notificationStore';
    import {
        SettingsButton,
        SettingsCard,
        SettingsCodeBlock,
        SettingsInfoBox,
        SettingsLoadingState,
        SettingsPageContainer,
        SettingsProgressBar,
        SettingsSectionHeading,
    } from '../elements';

    let isLoading = $state(true);
    let qrCodeSvg = $state('');

    let referralLink = $derived.by(() => {
        const code = $referralStatus?.referral_code;
        if (!code || typeof window === 'undefined') return '';
        return `${window.location.origin}/#ref=${code}`;
    });

    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    }

    function formatCurrency(cents: number): string {
        return `${(cents / 100).toFixed(0)} EUR`;
    }

    let progressPercent = $derived.by(() => {
        if (!$referralStatus?.max_successful_referrals) return 0;
        return ($referralStatus.successful_referrals_count / $referralStatus.max_successful_referrals) * 100;
    });

    function generateQRCode(link: string) {
        try {
            const qr = new QRCodeSVG({
                content: link,
                padding: 4,
                width: 180,
                height: 180,
                color: '#000000',
                background: '#ffffff',
                ecl: 'M',
            });
            qrCodeSvg = qr.svg();
        } catch (error) {
            console.error('[SettingsReferralCode] Failed to generate referral QR code:', error);
            qrCodeSvg = '';
        }
    }

    $effect(() => {
        if (referralLink) {
            generateQRCode(referralLink);
        } else {
            qrCodeSvg = '';
        }
    });

    async function copyReferralLink() {
        if (!referralLink) return;
        try {
            await navigator.clipboard.writeText(referralLink);
            notificationStore.success($text('settings.billing.referral_copied'));
        } catch (error) {
            console.error('[SettingsReferralCode] Failed to copy referral link:', error);
            notificationStore.error($text('settings.billing.referral_copy_failed'));
        }
    }

    onMount(async () => {
        isLoading = true;
        await loadReferralStatus();
        isLoading = false;
    });
</script>

<SettingsSectionHeading title={$text('settings.billing.referral_code')} icon="icon_gift" />

<SettingsPageContainer>
    {#if isLoading}
        <SettingsLoadingState text={$text('common.loading')} />
    {:else if !$referralStatus?.available || !referralLink}
        <SettingsInfoBox type="warning" icon="icon_gift">
            <p>{$text('settings.billing.referral_unavailable')}</p>
        </SettingsInfoBox>
    {:else}
        <SettingsCard ariaLabel={$text('settings.billing.referral_code')}>
            <div data-testid="referral-code-settings">
                <p>
                    {$text('settings.billing.referral_intro', {
                        values: {
                            referrerCredits: formatCredits($referralStatus.credits_per_referrer),
                            referredCredits: formatCredits($referralStatus.credits_per_referred_user)
                        }
                    })}
                </p>
            </div>
        </SettingsCard>

        <SettingsCodeBlock code={referralLink} wrap={false} dataTestid="referral-link" />

        <SettingsCard ariaLabel={$text('settings.billing.referral_qr_label')}>
            <div class="referral-qr-section">
                <p class="referral-qr-label">{$text('settings.billing.referral_qr_label')}</p>
                <div class="referral-qr-code" data-testid="referral-qr-code">
                    {#if qrCodeSvg}
                        <!-- eslint-disable-next-line svelte/no-at-html-tags -- QR code SVG is generated from trusted qrcode-svg library using the local referral link. -->
                        {@html qrCodeSvg}
                    {/if}
                </div>
            </div>
        </SettingsCard>

        <SettingsButton dataTestid="copy-referral-link" onClick={copyReferralLink} fullWidth>
            {$text('common.copy')}
        </SettingsButton>

        <SettingsProgressBar
            value={progressPercent}
            label={$text('settings.billing.referral_progress', {
                values: {
                    count: $referralStatus.successful_referrals_count,
                    max: $referralStatus.max_successful_referrals
                }
            })}
        />

        <SettingsInfoBox type="info" icon="icon_info">
            <p>
                {$text('settings.billing.referral_conditions', {
                    values: {
                        minPurchase: formatCurrency($referralStatus.min_purchase_amount_cents),
                        days: $referralStatus.attribution_expires_days,
                        max: $referralStatus.max_successful_referrals
                    }
                })}
            </p>
        </SettingsInfoBox>
    {/if}
</SettingsPageContainer>

<style>
    .referral-qr-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-5);
    }

    .referral-qr-label {
        margin: 0;
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
        font-weight: var(--font-weight-semibold);
        text-align: center;
    }

    .referral-qr-code {
        display: flex;
        width: 180px;
        height: 180px;
        align-items: center;
        justify-content: center;
        padding: var(--spacing-4);
        border-radius: var(--radius-4);
        background: var(--color-grey-0);
    }

    .referral-qr-code :global(svg) {
        display: block;
        width: 180px;
        height: 180px;
    }
</style>
