import type { FocusModeMetadata } from '../../types/apps';

type Translate = (key: string) => string;

/** Reject missing-key markers from both live translations and saved metadata. */
function authoredText(value: unknown, key?: string): string {
  if (typeof value !== 'string') return '';
  const text = value.trim();
  return text && !text.startsWith('[T:') && text !== key && text !== `${key}.text` ? text : '';
}

/** Prefer the selected locale; canonical authored text is an honest fallback. */
export function resolveFocusInstructions(focus: FocusModeMetadata | undefined, translate: Translate) {
  const promptKey = focus?.system_prompt_translation_key;
  const processKey = focus?.process_translation_key;
  const systemPrompt = (promptKey ? authoredText(translate(promptKey), promptKey) : '')
    || authoredText(focus?.system_prompt, promptKey);
  const translatedProcess = processKey ? authoredText(translate(processKey), processKey) : '';
  const processBullets = translatedProcess
    ? translatedProcess.split('\n').map(line => line.trim()).filter(line => /^[-*]\s+/.test(line))
      .map(line => line.replace(/^[-*]\s+/, '').trim()).filter(Boolean)
    : (focus?.process ?? []).map(value => authoredText(value)).filter(Boolean);
  return { systemPrompt, processBullets, hasInstructions: Boolean(systemPrompt || processBullets.length) };
}
