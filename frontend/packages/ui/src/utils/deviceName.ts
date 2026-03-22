/**
 * Generates a user-friendly device name from the user agent string.
 * Returns simple, recognizable names that users can easily identify.
 * 
 * @returns A device name like "MacBook", "iPhone", "Windows Device", etc.
 */
export function generateDeviceName(): string {
    if (typeof navigator === 'undefined') {
        return 'Unknown Device';
    }

    const ua = navigator.userAgent.toLowerCase();
    const platform = navigator.platform?.toLowerCase() || '';

    // Detect Mac devices
    if (platform.includes('mac') || ua.includes('macintosh')) {
        // Check if it's likely a MacBook (desktop Mac, not iPad)
        // iPad on iOS 13+ reports as MacIntel but has touch points
        if (navigator.maxTouchPoints > 1) {
            // Likely iPad
            return 'iPad';
        }
        // Check screen size to guess if it's a MacBook vs iMac
        // MacBooks typically have smaller screens, but this is a heuristic
        if (typeof window !== 'undefined' && window.screen && window.screen.width >= 1920) {
            return 'Mac';
        }
        return 'MacBook';
    }

    // Detect iPhone
    if (ua.includes('iphone') || (platform.includes('iphone'))) {
        return 'iPhone';
    }

    // Detect iPad (separate from Mac detection above)
    if (ua.includes('ipad') || (platform.includes('ipad'))) {
        return 'iPad';
    }

    // Detect Android devices
    if (ua.includes('android')) {
        // Try to detect if it's a phone or tablet
        if (ua.includes('mobile')) {
            return 'Android Phone';
        } else {
            return 'Android Tablet';
        }
    }

    // Detect Windows
    if (ua.includes('windows') || platform.includes('win')) {
        return 'Windows Device';
    }

    // Detect Linux
    if (ua.includes('linux') || platform.includes('linux')) {
        return 'Linux Device';
    }

    // Fallback
    return 'Unknown Device';
}

