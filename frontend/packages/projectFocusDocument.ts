/** Private saved Focus transport. Legacy conversion belongs to the server. */
export interface ProjectFocusRequirement {
  id: string;
  text: string;
  type?: "semantic" | "user_confirmation";
}
export interface CanonicalProjectFocusPhase {
  id: string;
  title: string;
  instructions: string;
  requirements: ProjectFocusRequirement[];
}
export interface LegacyProjectFocusPhase {
  id: string;
  name: string;
  instructions: string;
}
interface FocusDocumentBody {
  name: string;
  description: string;
  when_to_use: string;
  instructions: string;
}
export type ProjectFocusDocument = FocusDocumentBody & (
  | { phases_version: 1; phases: CanonicalProjectFocusPhase[] }
  | { phases_version?: never; phases: LegacyProjectFocusPhase[] }
);

function invalid(): never { throw new Error("invalid_focus_document"); }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, allowed: readonly string[]): void {
  if (Object.keys(value).some(key => !allowed.includes(key))) invalid();
}
function text(value: unknown, limit: number): string {
  if (typeof value !== "string" || !value.trim() || value.length > limit) return invalid();
  return value;
}
function identifier(value: unknown, canonical: boolean): string {
  const result = text(value, canonical ? 64 : 80);
  if (!(canonical ? /^[a-z][a-z0-9_-]{0,63}$/ : /^[a-zA-Z0-9_-]{1,80}$/).test(result)) invalid();
  return result;
}
function unique(ids: string[]): void {
  if (new Set(ids).size !== ids.length) invalid();
}

/** Validate decoded YAML without changing phase IDs, guidance or requirements. */
export function projectFocusDocumentFromMetadata(metadata: unknown, body: string): ProjectFocusDocument {
  const header = object(metadata);
  keys(header, ["name", "title", "description", "when_to_use", "preprocessor_hint", "preprocessor-hint", "phases_version", "phases"]);
  const names = [header.name, header.title].filter(value => value !== undefined);
  const hints = [header.when_to_use, header.preprocessor_hint, header["preprocessor-hint"]].filter(value => value !== undefined);
  if (names.length !== 1 || hints.length !== 1) invalid();
  const common = { name: text(names[0], 200), description: text(header.description, 2_000),
    when_to_use: text(hints[0], 2_000), instructions: text(body.trim(), 64_000) };
  const phases = header.phases === undefined ? [] : header.phases;
  if (!Array.isArray(phases) || phases.length > 16) invalid();
  // Presence, including null/boolean/unsupported values, forbids legacy fallback.
  if (Object.prototype.hasOwnProperty.call(header, "phases_version")) {
    if (header.phases_version !== 1 || !phases.length) invalid();
    const canonical = phases.map(raw => {
      const phase = object(raw);
      keys(phase, ["id", "title", "instructions", "requirements"]);
      const requirements = phase.requirements;
      if (!Array.isArray(requirements) || !requirements.length || requirements.length > 24) invalid();
      const gates = requirements.map(rawRequirement => {
        const requirement = object(rawRequirement);
        keys(requirement, ["id", "text", "type"]);
        if (requirement.type !== undefined && (typeof requirement.type !== "string" || !["semantic", "user_confirmation"].includes(requirement.type))) invalid();
        return { id: identifier(requirement.id, true), text: text(requirement.text, 4_000),
          ...(requirement.type === undefined ? {} : { type: requirement.type as ProjectFocusRequirement["type"] }) };
      });
      unique(gates.map(gate => gate.id));
      return { id: identifier(phase.id, true), title: text(phase.title, 200),
        instructions: text(phase.instructions, 16_000), requirements: gates };
    });
    unique(canonical.map(phase => phase.id));
    return { ...common, phases_version: 1, phases: canonical };
  }
  const legacy = phases.map(raw => {
    const phase = object(raw);
    keys(phase, ["id", "name", "instructions"]);
    return { id: identifier(phase.id, false), name: text(phase.name, 120), instructions: text(phase.instructions, 16_000) };
  });
  unique(legacy.map(phase => phase.id));
  return { ...common, phases: legacy };
}
