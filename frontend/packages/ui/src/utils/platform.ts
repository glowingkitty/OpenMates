export function isDesktop(): boolean {
    // The 'pointer: coarse' media query is a strong indicator of a touch-first device.
    // If the primary input method is coarse (like a finger), we should not treat it as a desktop
    // for the purpose of "Enter to send" functionality.
    if (typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches) {
        return false;
    }

    if (typeof navigator !== 'undefined') {
        // iPad on iOS 13+ may report as a Mac, but it's a touch device.
        if (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) {
            return false;
        }
        // Original user agent check as a final fallback.
        const mobileRegex = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i;
        if (mobileRegex.test(navigator.userAgent)) {
            return false;
        }
    }

    // If none of the mobile indicators are met, assume it's a desktop.
    return true;
}

export function isMobile(): boolean {
    return !isDesktop();
}
