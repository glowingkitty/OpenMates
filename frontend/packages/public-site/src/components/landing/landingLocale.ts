import copy from '../../generated/landingLocale.generated.json';

/** Public landing copy generated from the canonical YAML source. */
export const landingCopy = copy;
export type LandingLanguage = keyof typeof landingCopy;
