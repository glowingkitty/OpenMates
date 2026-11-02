/** Headless SDK Team trigger policy; no CLI/session/terminal module dependency. */
const SPECIALISTS = new Set([
  "software_development", "business_development", "life_coach_psychology", "medical_health",
  "legal_law", "finance", "design", "marketing_sales", "science", "history", "cooking_food",
  "electrical_engineering", "maker_prototyping", "movies_tv", "activism", "general_knowledge",
]);

export function shouldWaitForTeamAi(message: string, teamId: string | null): boolean {
  if (!teamId) return true;
  if (/(?:^|[^\w@])@openmates(?![\w-])/i.test(message)) return true;
  return Array.from(message.matchAll(/(?:^|[^\w@])@mate:([a-z0-9_-]+)(?![\w-])/gi))
    .some(match => SPECIALISTS.has(match[1].toLowerCase()));
}
