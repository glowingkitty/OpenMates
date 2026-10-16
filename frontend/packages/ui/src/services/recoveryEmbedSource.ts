/** Derive the exact source string represented by a version row from sealed embed TOON. */
export async function catalogContextFromSealedEmbed(
  content: string, producerApp: unknown, producerSkill: unknown,
): Promise<{ app_id: string; skill_id: string } | null> {
  let fields: Record<string, unknown> | null = null;
  if (producerApp === undefined || producerSkill === undefined) {
    let decoded: unknown = null;
    try {
      decoded = (await import("@toon-format/toon")).decode(content, { strict: false });
    } catch {
      try { decoded = JSON.parse(content); } catch { /* No catalog projection. */ }
    }
    if (decoded && typeof decoded === "object" && !Array.isArray(decoded)) {
      fields = decoded as Record<string, unknown>;
    }
  }
  const app = producerApp ?? fields?.app_id;
  const skill = producerSkill ?? fields?.skill_id;
  if (app === undefined && skill === undefined) return null;
  const catalogId = /^[a-z][a-z0-9_]{0,63}$/;
  if (typeof app !== "string" || !catalogId.test(app)
    || typeof skill !== "string" || !catalogId.test(skill)) {
    throw new Error("Recovered embed catalog identity was invalid.");
  }
  return { app_id: app, skill_id: skill };
}

export function isUnwrittenInitialDiffRead(status: number, detail: unknown, version: number): boolean {
  // Bounded version reads require a snapshot. Before a new v1 diff is stored,
  // there is no snapshot to anchor a chain, so the endpoint returns this 409.
  // Other conflicts remain pending; they must not authorize an overwrite.
  return version === 1 && status === 409 && detail === "snapshot_required";
}

export async function historySourceFromSealedEmbed(content: string, type: string): Promise<string> {
  const fieldByType: Record<string, string> = {
    code: "code", pcb_schematic: "code", sheet: "table", mermaid: "diagram_code",
  };
  const { decode } = await import("@toon-format/toon");
  const decoded = decode(content);
  if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)
    || (decoded as Record<string, unknown>).type !== type) {
    throw new Error("Sealed embed does not contain the expected historical source.");
  }
  const fields = decoded as Record<string, unknown>;
  if (type === "mail") {
    const components = ["receiver", "subject", "content", "footer"].map((field) => fields[field] ?? "");
    if (components.some((value) => typeof value !== "string")) {
      throw new Error("Sealed mail source has invalid fields.");
    }
    const [receiver, subject, body, footer] = components as string[];
    return [
      ...(receiver ? [`to: ${receiver}`] : []),
      ...(subject ? [`subject: ${subject}`] : []),
      "content:", ...(body ? [body] : []),
      ...(footer ? ["footer:", footer] : []),
    ].join("\n");
  }
  if (type === "document" || type === "notebook") {
    if (type === "document" && typeof fields.html === "string" && fields.html) return fields.html;
    const model = type === "document" ? fields.docx_model : fields.notebook;
    if (model && typeof model === "object" && !Array.isArray(model)) return JSON.stringify(model, null, 2);
    if (type === "notebook" && typeof fields.content === "string") return fields.content;
    throw new Error("Sealed document source has no supported historical body.");
  }
  const field = fieldByType[type];
  if (!field || typeof fields[field] !== "string") {
    throw new Error("Historical recovery does not know this embed source format.");
  }
  return fields[field] as string;
}
