import { describe, expect, it } from 'vitest';
import { formatRecipeNutrient, parseRecipeNutrition, parseRecipeResult } from './recipeNutrition';

// Actual first parent result from vegetarian-recipes-from-fridge-vegetables.
const edamamRecipe = {
  servings: 4,
  calories_per_serving: 390.32275000000004,
  nutrition_ENERC_KCAL_quantity: 1561.2910000000002,
  nutrition_ENERC_KCAL_unit: 'kcal',
  nutrition_PROCNT_quantity: 81.44995,
  nutrition_PROCNT_unit: 'g',
  nutrition_FAT_quantity: 28.041700000000002,
  nutrition_FAT_unit: 'g',
  nutrition_CHOCDF_quantity: 263.09475,
  nutrition_CHOCDF_unit: 'g',
  nutrition_FIBTG_quantity: 57.1817,
  nutrition_FIBTG_unit: 'g',
  nutrition_NA_quantity: 4882.112712,
  nutrition_NA_unit: 'mg'
};

describe('parseRecipeNutrition', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('formats serving fractions to at most one decimal without padding integers', () => {
    expect(formatRecipeNutrient(20.3624875)).toBe('20.4');
    expect(formatRecipeNutrient(14)).toBe('14');
    expect(formatRecipeNutrient(0)).toBe('0');
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('uses per-serving calories and divides real flattened Edamam totals by servings', () => {
    expect(parseRecipeNutrition(edamamRecipe)).toEqual({
      calories_kcal: 390.32275000000004,
      protein_g: 20.3624875,
      fat_g: 7.010425000000001,
      carbs_g: 65.7736875,
      fiber_g: 14.295425,
      sodium_mg: 1220.528178
    });
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('supports structured Edamam quantities and numeric strings', () => {
    expect(parseRecipeNutrition({ servings: '4', nutrition: {
      ENERC_KCAL: { quantity: '1561.291', unit: 'kcal' },
      PROCNT: { quantity: '81.44995', unit: 'g' },
      FAT: { quantity: 0, unit: 'g' }
    } })).toMatchObject({ calories_kcal: 390.32275, protein_g: 20.3624875, fat_g: 0 });
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('preserves legacy aliases and their already normalized values', () => {
    expect(parseRecipeNutrition({ ...edamamRecipe, nutrition: {
      calories_kcal: 520, nutrition_protein_g: '14g', nutrition_fat: '22',
      nutrition_carbohydrates: '68', nutrition_fiber: '6,5g', nutrition_sodium: 0
    } })).toEqual({ calories_kcal: 520, protein_g: 14, fat_g: 22, carbs_g: 68, fiber_g: 6.5, sodium_mg: 0 });
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it.each([undefined, 0, -1, 'invalid', '', NaN, Infinity])(
    'does not present whole-recipe macros as per-serving for servings=%s', (servings) => {
      expect(parseRecipeNutrition({ ...edamamRecipe, servings })).toMatchObject({
        calories_kcal: edamamRecipe.calories_per_serving, protein_g: undefined, fat_g: undefined
      });
    }
  );

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('does not mislabel missing units, incompatible units or invalid quantities', () => {
    expect(parseRecipeNutrition({ ...edamamRecipe,
      nutrition_PROCNT_unit: 'mg', nutrition_FAT_quantity: Infinity,
      nutrition_CHOCDF_quantity: -1, nutrition_FIBTG_unit: undefined
    })).toMatchObject({ protein_g: undefined, fat_g: undefined, carbs_g: undefined, fiber_g: undefined });
  });
});


// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
it('decodes saved direct-child ingredient fields, labels and per-serving macros', () => {
  const recipe = parseRecipeResult('saved-child', {
    ...edamamRecipe,
    title: 'Slow cooker chickpeas and spinach stew',
    ingredients: [{ text: '350 g of dry chickpeas, soaked in water for 12 hours', quantity: 350, measure: 'gram', food: 'chickpeas' }],
    instructions: [{ step: 1, text: 'Heat the oil in a small pan over high heat.' }],
    diet_labels: 'High-Fiber', health_labels: 'Vegan|Vegetarian', cuisine_type: 'american'
  });
  expect(recipe.embed_id).toBe('saved-child');
  expect(recipe.ingredients).toEqual([{ amount: undefined, unit: undefined, name: '350 g of dry chickpeas, soaked in water for 12 hours' }]);
  expect(recipe.instructions).toEqual([{ step: 1, text: 'Heat the oil in a small pan over high heat.' }]);
  expect(recipe.dietary_tags).toEqual(['High-Fiber', 'Vegan', 'Vegetarian']);
  expect(recipe.categories).toEqual(['american']);
  expect(recipe.nutrition?.protein_g).toBe(20.3624875);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
it('preserves legacy ingredients and falls back to provider ingredient lines', () => {
  expect(parseRecipeResult('legacy', { ingredients: [{ amount: '400', unit: 'g', name: 'Spaghetti' }] }).ingredients)
    .toEqual([{ amount: '400', unit: 'g', name: 'Spaghetti' }]);
  expect(parseRecipeResult('lines', { ingredient_lines: '1 carrot|½ red bell pepper' }).ingredients)
    .toEqual([{ name: '1 carrot' }, { name: '½ red bell pepper' }]);
});


// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
it('rejects overflowing numeric strings rather than reading their first digit', () => {
  expect(parseRecipeNutrition({ protein_g: '1e309' }).protein_g).toBeUndefined();
  expect(parseRecipeNutrition({ protein_g: 'Infinity' }).protein_g).toBeUndefined();
  expect(parseRecipeNutrition({ ...edamamRecipe, servings: '1e309' }).protein_g).toBeUndefined();
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
it('rejects overflowing unit-suffixed values while preserving valid legacy units and decimals', () => {
  expect(parseRecipeNutrition({ protein_g: `${'9'.repeat(400)} g` }).protein_g).toBeUndefined();
  expect(parseRecipeNutrition({ protein_g: '1e309 g' }).protein_g).toBeUndefined();
  expect(parseRecipeNutrition({ protein_g: '12 g', fat_g: '6,5 g' }))
    .toMatchObject({ protein_g: 12, fat_g: 6.5 });
});
