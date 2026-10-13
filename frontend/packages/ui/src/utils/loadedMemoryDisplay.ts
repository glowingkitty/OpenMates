import { get } from 'svelte/store';
import { text } from '../i18n/translations';
import { appSkillsStore } from '../stores/appSkillsStore';
import type { AppliedMemory } from './loadedMemoryReceipt';

/** A short, localized label for an applied guide, without exposing its document title. */
export function loadedMemoryName(memory: AppliedMemory): string {
  if (memory.source === 'app' && memory.app_id) {
    const app = appSkillsStore.getApp(memory.app_id);
    const definition = app?.memories?.find((item) => item.id === memory.id
      || memory.id === `app:${memory.app_id}:${item.id}`) as { name_translation_key?: string } | undefined;
    if (definition?.name_translation_key) {
      const translated = get(text)(definition.name_translation_key);
      if (translated && !translated.startsWith('[T:') && translated !== definition.name_translation_key) return translated;
    }
  }
  if (memory.source === 'app' && memory.id.startsWith(`app:${memory.app_id}:`)) {
    const suffix = memory.title.split(':').slice(1).join(':').trim();
    if (suffix) return suffix;
  }
  return memory.title;
}
