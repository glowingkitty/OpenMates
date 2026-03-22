/**
 * Default new chat suggestion keys (translation keys from i18n/locales/{locale}.json)
 * These are shown before the user signs up and has personalized suggestions
 *
 * IMPORTANT: These are translation keys, not the actual text
 * They will be translated at runtime using svelte-i18n
 *
 * Suggestions prefixed with [app_id-skill_id] expose skill discovery to new users.
 * The UI strips the prefix before inserting into the message input (body text only).
 */
export const DEFAULT_NEW_CHAT_SUGGESTION_KEYS = [
  // Discovery-oriented suggestions (expose app skills via [app_id-skill_id] prefix)
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
