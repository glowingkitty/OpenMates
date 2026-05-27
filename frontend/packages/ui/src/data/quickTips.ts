// frontend/packages/ui/src/data/quickTips.ts
// Stable registry for post-processing quick tips shown in chat.
//
// Backend stores only slugs in encrypted chat metadata. This registry maps each
// slug to local i18n keys and CTA behavior so UI copy remains deterministic,
// translated, and easy to review without changing the AI pipeline.

export type QuickTipAction = 'new_chat' | 'open_app' | 'send_prompt';

export interface QuickTipDefinition {
  slug: string;
  titleKey: string;
  bodyKey: string;
  ctaLabelKey?: string;
  ctaAction?: QuickTipAction;
  appId?: string;
  promptKey?: string;
}

const LEARN_MORE_CTA_KEY = 'chat.quick_tips.cta_learn_more';

export const QUICK_TIPS: Record<string, QuickTipDefinition> = {
  'shorter-chats-equal-better-responses': {
    slug: 'shorter-chats-equal-better-responses',
    titleKey: 'chat.quick_tips.shorter_chats_equal_better_responses.title',
    bodyKey: 'chat.quick_tips.shorter_chats_equal_better_responses.body',
    ctaLabelKey: LEARN_MORE_CTA_KEY,
    ctaAction: 'new_chat',
  },
  'search-current-info-next-time': {
    slug: 'search-current-info-next-time',
    titleKey: 'chat.quick_tips.search_current_info_next_time.title',
    bodyKey: 'chat.quick_tips.search_current_info_next_time.body',
    ctaLabelKey: LEARN_MORE_CTA_KEY,
    ctaAction: 'open_app',
    appId: 'web',
  },
  'travel-can-add-local-context': {
    slug: 'travel-can-add-local-context',
    titleKey: 'chat.quick_tips.travel_can_add_local_context.title',
    bodyKey: 'chat.quick_tips.travel_can_add_local_context.body',
    ctaLabelKey: LEARN_MORE_CTA_KEY,
    ctaAction: 'open_app',
    appId: 'travel',
  },
  'use-apps-for-better-results': {
    slug: 'use-apps-for-better-results',
    titleKey: 'chat.quick_tips.use_apps_for_better_results.title',
    bodyKey: 'chat.quick_tips.use_apps_for_better_results.body',
    ctaLabelKey: LEARN_MORE_CTA_KEY,
    ctaAction: 'open_app',
  },
};

export function getQuickTip(slug: string): QuickTipDefinition | null {
  return QUICK_TIPS[slug] ?? null;
}
