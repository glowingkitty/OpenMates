// frontend/packages/ui/src/components/embeds/embedDataUtils.ts
// Primitive coercion helpers shared by embed metadata normalizers.
// Keep these helpers side-effect-free so preview routes, chat rendering, and
// example chat rendering can normalize snapshot payloads deterministically.
// App-specific normalizers remain in each embed folder.

export function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim().length > 0 ? value : undefined;
}

export function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}
