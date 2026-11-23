/**
 * Registry for the locally decrypted Project names that mentions display.
 *
 * The Project service registers a lookup at runtime; display code (mention
 * previews, titles and composer chips) reads it here. Kept free of imports so
 * lightweight modules like the composer's markdown parser can use it without
 * pulling in services or stores.
 */

/** Looks up a Project's decrypted name on this device; undefined when it is not known. */
export type ProjectNameLookup = (projectId: string) => string | null | undefined;

let registeredProjectNameLookup: ProjectNameLookup | null = null;

/** Lets the Project service supply locally decrypted Project names for mentions. */
export function registerMentionProjectNameLookup(lookup: ProjectNameLookup | null): void {
  registeredProjectNameLookup = lookup;
}

/** The registered lookup, or null before the Project service registered one. */
export function projectNameLookup(): ProjectNameLookup | null {
  return registeredProjectNameLookup;
}

/** A Project's name when this device knows it, for mention chips and labels. */
export function knownProjectMentionName(projectId: string): string | undefined {
  return registeredProjectNameLookup?.(projectId)?.trim() || undefined;
}

/** Fetches the names of the given Projects into the lookup; never rejects. */
export type ProjectNameResolver = (projectIds: string[]) => Promise<void>;

let registeredProjectNameResolver: ProjectNameResolver | null = null;

/** Lets the Project service fetch names that the lookup does not know yet. */
export function registerMentionProjectNameResolver(resolver: ProjectNameResolver | null): void {
  registeredProjectNameResolver = resolver;
}

/** Fetches missing Project names; a no-op until the Project service registered a resolver. */
export async function resolveProjectMentionNamesById(projectIds: string[]): Promise<void> {
  if (projectIds.length) await registeredProjectNameResolver?.(projectIds);
}
