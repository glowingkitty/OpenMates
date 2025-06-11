export function isDesktop(): boolean {
    const mobileRegex = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i;
    return !mobileRegex.test(navigator.userAgent);
}

export function isMobile(): boolean {
    return !isDesktop();
}
