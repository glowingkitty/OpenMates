import { installAppCatalogPreview } from '../apps/appCatalogPreview';

export default { activeSettingsView: 'apps/web' };
export const variants = {
  catalogWeb: { activeSettingsView: 'apps/web' },
  catalogBlockedApp: { activeSettingsView: 'apps/openmates' },
};
export const ready = (() => {
  if (typeof window !== 'undefined') installAppCatalogPreview();
})();
