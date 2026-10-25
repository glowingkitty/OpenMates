/** Actual authored source content for isolated instructions display verification. */
import { addMessages, locale, waitLocale } from 'svelte-i18n';
import YAML from 'yaml';
import sourceYaml from '../../i18n/sources/focus_modes/social_media_content_calendar_strategist.yml?raw';
import { appsMetadata } from '../../data/appsMetadata';
import { appSkillsStore } from '../../stores/appSkillsStore';
import type { FocusModeMetadata } from '../../types/apps';

export default { appId: 'social_media', focusModeId: 'content_calendar_strategist' };
export const variants = {
  empty: { appId: 'code', focusModeId: 'analyze_logs' },
  staleReferences: { appId: 'code', focusModeId: 'analyze_logs' },
};

export const ready = (async () => {
  if (typeof window === 'undefined') return;
  const params = new URLSearchParams(window.location.search);
  const language = params.get('lang') === 'de' ? 'de' : 'en';
  locale.set(language);
  await waitLocale(language);
  const source = YAML.parse(sourceYaml);
  addMessages(language, { focus_modes: { social_media_content_calendar_strategist: {
    systemprompt: { text: source.systemprompt[language] },
  } } });
  const social: FocusModeMetadata = {
    id: 'content_calendar_strategist',
    name_translation_key: 'app_focus_modes.social_media.content_calendar_strategist',
    description_translation_key: 'app_focus_modes.social_media.content_calendar_strategist.description',
    system_prompt: source.systemprompt.en,
    system_prompt_translation_key: 'focus_modes.social_media_content_calendar_strategist.systemprompt',
  };
  const empty: FocusModeMetadata = {
    id: 'analyze_logs', name_translation_key: 'app_focus_modes.code.analyze_logs',
    description_translation_key: 'app_focus_modes.code.analyze_logs.description',
    ...(params.get('variant') === 'staleReferences' ? {
      system_prompt_translation_key: 'focus_modes.code_analyze_logs.systemprompt',
      process_translation_key: 'focus_modes.code_analyze_logs.process',
    } : {}),
  };
  const original = appSkillsStore.getState;
  const apps = {
    ...appsMetadata,
    social_media: { ...appsMetadata.social_media, focus_modes: [social] },
    code: { ...appsMetadata.code, focus_modes: [empty] },
  };
  appSkillsStore.getState = () => ({ apps });
  window.addEventListener('pagehide', () => { appSkillsStore.getState = original; }, { once: true });
})();
