/** Small, allowlisted email preview. Never include messages, full embeds, or URLs. */
export interface ReminderNotificationContext {
  version: 1;
  kind: 'chat' | 'event' | 'appointment' | 'travel_connection' | 'travel_stay' | 'home_listing' | 'embed';
  title: string;
  description?: string;
  summary?: string;
  icon?: string;
  category?: string;
  app_id?: string;
  starts_at?: string;
  ends_at?: string;
  timezone?: string;
  location?: string;
  facts?: Array<{ label: string; value: string }>;
  image_base64?: string;
}

type Fields = Record<string, unknown>;
function bounded(value: unknown, limit: number): string | undefined {
  if (typeof value !== 'string' && typeof value !== 'number') return undefined;
  if (typeof value === 'number' && !Number.isFinite(value)) return undefined;
  const text = String(value).replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, ' ').replace(/<[^>]*>/g, ' ').replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&quot;/gi, '"').replace(/&#39;/gi, "'");
  const result = Array.from(text).filter((char) => {
    const code = char.charCodeAt(0);
    return code === 9 || code === 10 || code === 13 || (code >= 32 && code !== 127);
  }).join('').trim();
  return result ? Array.from(result).slice(0, limit).join('') : undefined;
}
function first(fields: Fields, keys: string[]): unknown {
  return keys.map((key) => fields[key]).find((value) => bounded(value, 1));
}
function iso(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length > 80 || !/^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value)) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

export function buildReminderNotificationContext(
  kind: ReminderNotificationContext['kind'] | 'health_appointment',
  title: string,
  fields: Fields = {},
  appId?: string,
): ReminderNotificationContext {
  const context: ReminderNotificationContext = {
    version: 1,
    kind: kind === 'health_appointment' ? 'appointment' : kind,
    title: bounded(title, 200) || 'Reminder',
  };
  const textFields: Array<[keyof ReminderNotificationContext, unknown, number]> = [
    ['description', fields.description, 2000], ['summary', fields.summary, 500],
    ['icon', fields.icon, 64], ['category', fields.category, 64], ['app_id', appId, 64],
    ['location', first(fields, ['location', 'address', 'where']), 1000],
  ];
  for (const [key, value, limit] of textFields) {
    const text = bounded(value, limit);
    if (text) Object.assign(context, { [key]: text });
  }
  const starts = iso(first(fields, ['date_start', 'departure', 'slot_datetime', 'appointment_time', 'check_in', 'check_in_date', 'available_from']));
  const ends = iso(first(fields, ['date_end', 'arrival', 'check_out', 'check_out_date']));
  if (starts) context.starts_at = starts;
  if (ends) context.ends_at = ends;
  const timezone = bounded(fields.timezone, 64);
  if (timezone) {
    try { new Intl.DateTimeFormat('en', { timeZone: timezone }); context.timezone = timezone; } catch { /* omit invalid zones */ }
  }
  const factFields = [
    ['Provider', ['provider', 'booking_provider']], ['From', ['origin']], ['To', ['destination']],
    ['Transport', ['transport_method']], ['Price', ['price', 'price_label']],
    ['Duration', ['duration']], ['Property type', ['property_type']], ['Speciality', ['speciality']],
  ] as const;
  const facts: NonNullable<ReminderNotificationContext['facts']> = [];
  for (const [label, keys] of factFields) {
    const value = bounded(first(fields, [...keys]), 512);
    if (value) facts.push({ label, value });
  }
  if (facts.length) context.facts = facts;
  // Leave room for the server JSON encoder's whitespace. Keep descriptions ahead
  // of secondary facts/location when multi-byte text reaches the total budget.
  const encoder = new TextEncoder();
  const bytes = () => encoder.encode(JSON.stringify(context)).length;
  while (bytes() > 7800 && context.facts?.length) context.facts.pop();
  if (!context.facts?.length) delete context.facts;
  for (const key of ['location', 'summary', 'description'] as const) {
    while (bytes() > 7800 && context[key]) {
      const chars = Array.from(context[key]);
      context[key] = chars.slice(0, Math.max(0, chars.length - 100)).join('');
      if (!context[key]) delete context[key];
    }
  }
  return context;
}

/** Optional browser-only image preview; failures must never prevent scheduling. */
export async function captureReminderThumbnail(rawUrl: unknown): Promise<string | undefined> {
  if (typeof rawUrl !== 'string' || !rawUrl || typeof document === 'undefined'
    || typeof createImageBitmap !== 'function') return undefined;
  // imageProxy intentionally passes data: and // URLs through; reject them here.
  const relative = rawUrl.startsWith('/') && !rawUrl.startsWith('//') && !rawUrl.startsWith('/\\');
  if (!/^https?:\/\//i.test(rawUrl) && !relative) return undefined;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  let bitmap: ImageBitmap | undefined;
  try {
    const { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } = await import('./imageProxy');
    const response = await fetch(proxyImage(rawUrl, MAX_WIDTH_PREVIEW_THUMBNAIL), {
      credentials: 'omit', signal: controller.signal,
    });
    if (!response.ok) return undefined;
    const blob = await response.blob();
    if (!/^image\/(?:jpeg|png|webp)$/i.test(blob.type) || blob.size > 2 * 1024 * 1024) return undefined;
    bitmap = await createImageBitmap(blob);
    if (!bitmap.width || !bitmap.height) return undefined;
    const scale = Math.min(1, 600 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d');
    if (!context) return undefined;
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    for (const quality of [0.78, 0.55, 0.35]) {
      const encoded = canvas.toDataURL('image/jpeg', quality);
      if (!encoded.startsWith('data:image/jpeg;base64,')) return undefined;
      const base64 = encoded.slice('data:image/jpeg;base64,'.length);
      if (base64 && base64.length <= 160 * 1024) return base64;
    }
  } catch {
    // CORS, proxy, decode and canvas failures all use the metadata-only card.
  } finally {
    clearTimeout(timer);
    bitmap?.close();
  }
  return undefined;
}
