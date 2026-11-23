// A stored Google account label is "legacy" when it is empty or only the generic provider
// name written before the OAuth flow learned the account email. Emails and user-chosen
// names are shown as they are.
const GENERIC_GOOGLE_LABELS = new Set(['', 'google calendar', 'gmail', 'google mail', 'google account']);

export function isLegacyGoogleLabel(label: string | null | undefined): boolean {
	return GENERIC_GOOGLE_LABELS.has((label ?? '').trim().toLowerCase());
}
