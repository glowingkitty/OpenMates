/**
 * Utility functions for chat categories and gradient colors
 */

import * as LucideIcons from '@lucide/svelte';

/**
 * Category gradient colors configuration
 */
export const CATEGORY_GRADIENTS: Record<string, { start: string; end: string }> = {
  'software_development': { start: '#155D91', end: '#42ABF4' },
  'business_development': { start: '#004040', end: '#008080' },
  'medical_health': { start: '#FD50A0', end: '#F42C2D' },
  'legal_law': { start: '#239CFF', end: '#005BA5' }, // Legacy - kept for backwards compatibility
  'openmates_official': { start: '#6366f1', end: '#4f46e5' }, // Official OpenMates brand colors (indigo)
  'maker_prototyping': { start: '#EA7600', end: '#FBAB59' },
  'marketing_sales': { start: '#FF8C00', end: '#F4B400' },
  'finance': { start: '#119106', end: '#15780D' },
  'design': { start: '#101010', end: '#2E2E2E' },
  'electrical_engineering': { start: '#233888', end: '#2E4EC8' },
  'movies_tv': { start: '#00C2C5', end: '#3170DC' },
  'history': { start: '#4989F2', end: '#2F44BF' },
  'science': { start: '#FF7300', end: '#D5320' },
  'life_coach_psychology': { start: '#FDB250', end: '#F42C2D' },
  'cooking_food': { start: '#FD8450', end: '#F42C2D' },
  'activism': { start: '#F53D00', end: '#F56200' },
  'general_knowledge': { start: '#DE1E66', end: '#FF763B' }
};

/**
 * Fallback icons for categories
 */
export const CATEGORY_FALLBACK_ICONS: Record<string, string> = {
  'software_development': 'code',
  'business_development': 'briefcase',
  'medical_health': 'heart',
  'legal_law': 'gavel', // Legacy - kept for backwards compatibility
  'openmates_official': 'shield-check', // Official category uses shield icon
  'maker_prototyping': 'wrench',
  'marketing_sales': 'megaphone',
  'finance': 'dollar-sign',
  'design': 'palette',
  'electrical_engineering': 'zap',
  'movies_tv': 'tv',
  'history': 'clock',
  'science': 'microscope',
  'life_coach_psychology': 'users',
  'cooking_food': 'utensils',
  'activism': 'trending-up',
  'general_knowledge': 'help-circle'
};

/**
 * Get gradient colors for a category
 */
export function getCategoryGradientColors(category: string): { start: string; end: string } | null {
  return CATEGORY_GRADIENTS[category] || null;
}

/**
 * Get fallback icon for a category
 */
export function getFallbackIconForCategory(category: string): string {
  return CATEGORY_FALLBACK_ICONS[category] || 'help-circle';
}

/**
 * Check if a string is a valid Lucide icon name
 */
export function isValidLucideIcon(iconName: string): boolean {
  if (!iconName) return false;
  
  // Convert kebab-case to PascalCase (e.g., 'help-circle' -> 'HelpCircle')
  const pascalCaseName = iconName
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join('');
  
  return pascalCaseName in LucideIcons;
}

/**
 * Get a valid icon name with robust fallback system
 */
export function getValidIconName(providedIconNames: string | string[], category: string): string {
  const iconNames = Array.isArray(providedIconNames) ? providedIconNames : [providedIconNames];
  
  // Try each provided icon name in order
  for (const iconName of iconNames) {
    if (isValidLucideIcon(iconName)) {
      return iconName;
    }
  }

  // If no valid icons provided, use category-specific fallback
  const categoryFallback = getFallbackIconForCategory(category);
  if (isValidLucideIcon(categoryFallback)) {
    return categoryFallback;
  }

  // Final safety net
  return 'help-circle';
}

/**
 * Get the Lucide icon component by name
 * Returns a Svelte component type
 */
export function getLucideIcon(iconName: string): typeof LucideIcons.HelpCircle {
  if (!iconName) return LucideIcons.HelpCircle;
  
  // Convert kebab-case to PascalCase (e.g., 'help-circle' -> 'HelpCircle')
  const pascalCaseName = iconName
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join('');
  
  // Dynamic access to LucideIcons (property names are determined at runtime)
  // Type assertion needed because property access is dynamic
  const icon = (LucideIcons as unknown as Record<string, typeof LucideIcons.HelpCircle>)[pascalCaseName];
  return icon || LucideIcons.HelpCircle;
}
