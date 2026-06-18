/**
 * Default new chat suggestion keys (translation keys from i18n/locales/{locale}.json)
 * These are shown before the user signs up and has personalized suggestions
 *
 * IMPORTANT: These are translation keys, not the actual text
 * They will be translated at runtime using svelte-i18n
 *
 * Suggestions are plain natural-language prompts. Skill discovery happens through
 * wording that the app-skill router can auto-detect, not visible prefixes.
 */
export const DEFAULT_NEW_CHAT_SUGGESTION_KEYS = [
  // Discovery-oriented suggestions written to naturally trigger app skills
  "chat.new_chat_suggestions.discover_web_search",
  "chat.new_chat_suggestions.discover_image_generate",
  "chat.new_chat_suggestions.discover_news_search",
  "chat.new_chat_suggestions.discover_video_search",
  "chat.new_chat_suggestions.discover_math_calculate",
  // General knowledge suggestions (no prefix — pure text queries)
  "chat.new_chat_suggestions.quantum_computing",
  "chat.new_chat_suggestions.plan_trip_japan",
  "chat.new_chat_suggestions.ai_news",
  "chat.new_chat_suggestions.photosynthesis",
  "chat.new_chat_suggestions.professional_email",
  "chat.new_chat_suggestions.healthy_breakfast",
  "chat.new_chat_suggestions.blockchain",
  "chat.new_chat_suggestions.learn_spanish",
  "chat.new_chat_suggestions.ml_vs_ai",
  "chat.new_chat_suggestions.improve_productivity",
  "chat.new_chat_suggestions.theory_relativity",
  "chat.new_chat_suggestions.workout_plan",
  "chat.new_chat_suggestions.cybersecurity",
  "chat.new_chat_suggestions.learn_coding",
  "chat.new_chat_suggestions.stock_market",
  "chat.new_chat_suggestions.cover_letter",
  "chat.new_chat_suggestions.writing_prompts",
  "chat.new_chat_suggestions.carbon_footprint",
  "chat.new_chat_suggestions.internet_history",
  "chat.new_chat_suggestions.meal_prep",
];
