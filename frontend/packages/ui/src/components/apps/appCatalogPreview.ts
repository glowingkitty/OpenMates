import { appSkillsStore, resetFeatureAvailability, userAvailableSkillsStore } from '../../stores/appSkillsStore';

/** Synthetic runtime availability over real build-time metadata; no account or provider calls. */
export function installAppCatalogPreview(): void {
  if (typeof window === 'undefined') return;
  resetFeatureAvailability();
  const apps = appSkillsStore.getState().apps;
  const publish = (hideWeb = false) => {
    const selected = Object.fromEntries(Object.entries(apps).filter(([id]) => !hideWeb || id !== 'web'));
    userAvailableSkillsStore.set({ initialized: true, loading: false, appsById: selected,
      skillsByApp: Object.fromEntries(Object.entries(selected).map(([id, app]) => [id, app.skills.map(skill => skill.id)])) });
  };
  publish();
  window.addEventListener('catalog-preview-hide-web', () => publish(true));
}
