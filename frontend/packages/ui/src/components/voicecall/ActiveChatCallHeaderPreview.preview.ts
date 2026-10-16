/** Actual mobile toolbar and fixed Settings profile, without an account. */
export const layout = 'fill';
export default { direction: 'ltr' as const };
export const variants = {
  rtl: { direction: 'rtl' as const },
  header: { direction: 'ltr' as const, withHeader: true },
  headerViewport: { direction: 'ltr' as const, withHeader: true, viewportAligned: true },
  headerRtl: { direction: 'rtl' as const, withHeader: true },
  privateCall: { direction: 'ltr' as const, withHeader: true },
  demoCall: { direction: 'ltr' as const, withHeader: true, viewportAligned: true },
};
