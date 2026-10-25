import { installAppCatalogPreview } from '../apps/appCatalogPreview';

export default {};
export const layout = 'fill';
export const variants = { catalogAvailability: {} };
export const ready = (() => {
  if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('variant') === 'catalogAvailability') installAppCatalogPreview();
})();
