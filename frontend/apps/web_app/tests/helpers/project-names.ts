/**
 * Natural-language Project names for tests.
 *
 * Tests of Project features use names a person would actually give a Project
 * ("Kitchen renovation", "Spanish lessons"), never timestamps or random ids:
 * digit runs are unrealistic, read badly in recordings and trip number-based
 * checks such as the composer's sensitive-data preview. When several Projects
 * may share one account at once (parallel workers, retries), the name gets a
 * random natural two-word nickname instead of a number.
 *
 * Rule: `.claude/rules/testing.md` ("Project names").
 */

const ADJECTIVES = [
	'amber', 'bright', 'calm', 'cedar', 'clear', 'coastal', 'copper', 'crisp', 'eastern', 'evening',
	'gentle', 'golden', 'green', 'hidden', 'island', 'lively', 'lunar', 'maple', 'meadow', 'misty',
	'morning', 'northern', 'olive', 'quiet', 'river', 'rustic', 'silver', 'snowy', 'sunny', 'velvet',
] as const;

const NOUNS = [
	'harbor', 'garden', 'valley', 'orchard', 'lantern', 'bridge', 'cabin', 'canyon', 'forest', 'meadow',
	'library', 'market', 'studio', 'workshop', 'terrace', 'lighthouse', 'pond', 'trail', 'village', 'kitchen',
	'balcony', 'atelier', 'courtyard', 'greenhouse', 'harvest', 'journey', 'notebook', 'compass', 'island', 'summit',
] as const;

function pick<T>(items: readonly T[]): T {
	return items[Math.floor(Math.random() * items.length)];
}

/** A random two-word nickname such as "quiet harbor". */
export function naturalNickname(): string {
	return `${pick(ADJECTIVES)} ${pick(NOUNS)}`;
}

/**
 * A readable, practically unique Project name: the topic plus a nickname,
 * e.g. `naturalProjectName('Kitchen renovation')` -> "Kitchen renovation: quiet harbor".
 * The last word is a plain word, so mention search can type it.
 */
export function naturalProjectName(topic: string): string {
	return `${topic}: ${naturalNickname()}`;
}
