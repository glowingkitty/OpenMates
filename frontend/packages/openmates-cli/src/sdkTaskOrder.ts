/** Stateless task ordering through the shared Rust SDK. No client or auth. */
import { loadSdkWasm } from "./sdkWasm.js";
import { SessionClientError } from "./sdkSession.js";

export interface TaskOrderRow {
  position?: number | null;
  title?: string | null;
  source?: string | null;
  [field: string]: unknown;
}
export type TaskOrderOptions = { locale: string };

function invalid(): never {
  throw new SessionClientError("invalid_argument", "Supply task rows and an explicit locale.");
}
function nativeOrder(encoded: string): string {
  const native = loadSdkWasm();
  if (!native) throw new SessionClientError("native_binding_unavailable", "Install an OpenMates SDK build containing its WebAssembly module.");
  return native.taskOrder(encoded);
}

/** Return a new array containing the same row objects, in shared SDK order. */
export function sortTasks<T extends TaskOrderRow>(tasks: readonly T[], options: TaskOrderOptions): T[] {
  try {
    if (!Array.isArray(tasks) || !options || typeof options !== "object" || Array.isArray(options) || !Object.hasOwn(options,"locale") || typeof options.locale !== "string" || Reflect.ownKeys(options).some(key => key !== "locale")) invalid();
    // Unknown row metadata stays with the caller, including non-JSON values.
    // Only comparison fields cross the native boundary; never coerce NaN to null.
    const rows = tasks.map(row => {
      if (!row || typeof row !== "object" || Array.isArray(row)) invalid();
      const projected: TaskOrderRow = {};
      for (const field of ["position", "title", "source"] as const) {
        if (!Object.hasOwn(row, field)) continue;
        const value = row[field];
        if (value !== null && (field === "position" ? typeof value !== "number" || !Number.isFinite(value) : typeof value !== "string")) invalid();
        Object.assign(projected, { [field]: value });
      }
      return projected;
    });
    const result: unknown = JSON.parse(nativeOrder(JSON.stringify({ locale: options.locale, tasks: rows })));
    const indices = (result as { indices?: unknown })?.indices;
    if (!Array.isArray(indices) || indices.length !== tasks.length || new Set(indices).size !== tasks.length || indices.some(index => !Number.isSafeInteger(index) || index < 0 || index >= tasks.length)) {
      throw new SessionClientError("protocol", "The native task order is invalid.");
    }
    return indices.map(index => tasks[index]);
  } catch (error) {
    if (error instanceof SessionClientError) throw error;
    try {
      const value = JSON.parse(error instanceof Error ? error.message : "");
      if (typeof value.code === "string" && typeof value.message === "string") throw new SessionClientError(value.code, value.message);
    } catch (mapped) { if (mapped instanceof SessionClientError) throw mapped; }
    throw new SessionClientError("native_failure", "The native task ordering operation failed.");
  }
}
