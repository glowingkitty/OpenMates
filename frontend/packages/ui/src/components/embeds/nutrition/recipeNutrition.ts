/** Normalize recipe nutrition to the per-serving values used by recipe details. */
export interface RecipeNutrition {
  calories_kcal?: number;
  protein_g?: number;
  fat_g?: number;
  carbs_g?: number;
  fiber_g?: number;
  sodium_mg?: number;
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const direct = Number(value);
  if (!Number.isNaN(direct)) return Number.isFinite(direct) ? direct : undefined;
  const leading = value.match(/-?\d+(?:[.,]\d+)?(?:e[+-]?\d+)?/i);
  if (!leading) return undefined;
  const parsed = Number(leading[0].replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function parseRecipeNutrition(content: Record<string, unknown>): RecipeNutrition {
  const raw = content.nutrition;
  const nutrition = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown> : content;
  const servings = asNumber(content.servings);

  // Edamam's coded quantities are whole-recipe totals (totalNutrients).
  // Do not mix these with per-serving calories when the serving count is unknown.
  function perServing(code: string, unit: string): number | undefined {
    if (servings == null || servings <= 0) return undefined;
    const rawNutrient = nutrition[code];
    const nutrient = rawNutrient && typeof rawNutrient === 'object'
      ? rawNutrient as Record<string, unknown> : undefined;
    const quantity = asNumber(nutrient?.quantity ?? content[`nutrition_${code}_quantity`]);
    const actualUnit = nutrient?.unit ?? content[`nutrition_${code}_unit`];
    if (quantity == null || quantity < 0 || actualUnit !== unit) return undefined;
    const value = quantity / servings;
    return Number.isFinite(value) ? value : undefined;
  }

  return {
    calories_kcal: asNumber(nutrition.calories_kcal ?? nutrition.nutrition_calories_kcal
      ?? nutrition.calories_per_serving ?? nutrition.nutrition_energy ?? content.calories_per_serving)
      ?? perServing('ENERC_KCAL', 'kcal'),
    protein_g: asNumber(nutrition.protein_g ?? nutrition.nutrition_protein_g ?? nutrition.nutrition_protein)
      ?? perServing('PROCNT', 'g'),
    fat_g: asNumber(nutrition.fat_g ?? nutrition.nutrition_fat_g ?? nutrition.nutrition_fat)
      ?? perServing('FAT', 'g'),
    carbs_g: asNumber(nutrition.carbs_g ?? nutrition.nutrition_carbs_g ?? nutrition.nutrition_carbohydrates)
      ?? perServing('CHOCDF', 'g'),
    fiber_g: asNumber(nutrition.fiber_g ?? nutrition.nutrition_fiber_g ?? nutrition.nutrition_fiber)
      ?? perServing('FIBTG', 'g'),
    sodium_mg: asNumber(nutrition.sodium_mg ?? nutrition.nutrition_sodium_mg ?? nutrition.nutrition_sodium)
      ?? perServing('NA', 'mg')
  };
}

/** Keep computed serving fractions readable without discarding source precision. */
export function formatRecipeNutrient(value: number): string {
  return String(Math.round(value * 10) / 10);
}

export interface RecipeResult {
  embed_id: string;
  title?: string;
  description?: string;
  image_url?: string | null;
  recipe_url?: string;
  prep_time_minutes?: number | null;
  cook_time_minutes?: number | null;
  total_time_minutes?: number | null;
  difficulty?: string | null;
  servings?: number | null;
  rating?: number | null;
  rating_count?: number | null;
  ernaehrwert_score?: number | null;
  dietary_tags?: string[];
  categories?: string[];
  ingredients?: Array<{ amount?: string; unit?: string; name: string }>;
  instructions?: Array<{ step?: number; text: string }>;
  nutrition?: RecipeNutrition;
}

function asString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.toLowerCase() !== 'null' ? trimmed : undefined;
}

function parseDelimitedList(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string');
  const raw = asString(value);
  return raw ? raw.split('|').map((item) => item.trim()).filter(Boolean) : [];
}

function parseMergedList(...values: unknown[]): string[] {
  return [...new Set(values.flatMap(parseDelimitedList))];
}

function parseIngredients(content: Record<string, unknown>): RecipeResult['ingredients'] {
  const raw = content.ingredients ?? content.ingredient_lines;
  if (typeof raw === 'string') {
    return parseDelimitedList(raw).map((name) => ({ name }));
  }
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
    .map((item) => ({
      amount: asString(item.amount),
      unit: asString(item.unit),
      name: asString(item.name) ?? asString(item.text) ?? asString(item.food) ?? ''
    }));
}

function parseInstructions(content: Record<string, unknown>): RecipeResult['instructions'] {
  const raw = content.instructions;
  if (typeof raw === 'string') {
    return parseDelimitedList(raw).map((text, index) => ({ step: index + 1, text }));
  }
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
    .map((item) => ({
      step: asNumber(item.step),
      text: typeof item.text === 'string' ? item.text : ''
    }));
}

export function parseRecipeResult(embedId: string, content: Record<string, unknown>): RecipeResult {
  return {
    embed_id: asString(content.embed_id) || embedId,
    title: asString(content.title),
    description: asString(content.description),
    image_url: asString(content.image_url) || null,
    recipe_url: asString(content.recipe_url),
    prep_time_minutes: asNumber(content.prep_time_minutes) ?? null,
    cook_time_minutes: asNumber(content.cook_time_minutes) ?? null,
    total_time_minutes: asNumber(content.total_time_minutes) ?? null,
    difficulty: asString(content.difficulty) || null,
    servings: asNumber(content.servings) ?? null,
    rating: asNumber(content.rating) ?? null,
    rating_count: asNumber(content.rating_count) ?? null,
    ernaehrwert_score: asNumber(content.ernaehrwert_score) ?? null,
    dietary_tags: parseMergedList(content.dietary_tags, content.diet_labels, content.health_labels),
    categories: parseMergedList(content.categories, content.cuisine_type, content.meal_type, content.dish_type),
    ingredients: parseIngredients(content),
    instructions: parseInstructions(content),
    nutrition: parseRecipeNutrition(content)
  };
}
