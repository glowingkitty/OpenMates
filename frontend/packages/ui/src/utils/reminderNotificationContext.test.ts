import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildReminderNotificationContext, captureReminderThumbnail } from './reminderNotificationContext';

vi.mock('./imageProxy', () => ({
  MAX_WIDTH_PREVIEW_THUMBNAIL: 520,
  proxyImage: (url: string, width: number) => `/proxy?url=${encodeURIComponent(url)}&max_width=${width}`,
}));

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('reminder email context', () => {
  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
  it('captures description, dates, location and travel facts, excluding full content and URLs', () => {
    const context = buildReminderNotificationContext('travel_connection', 'Berlin → Paris', {
      description: '<p>Direct <b>train</b> &amp; seat reservation</p>',
      departure: '2027-03-20T08:00:00+01:00', arrival: '2027-03-20T16:00:00+01:00',
      timezone: 'Europe/Berlin', location: 'Berlin Hbf', origin: 'Berlin', destination: 'Paris',
      booking_provider: 'Rail provider', transport_method: 'train', price: 'EUR 90',
      messages: ['private'], booking_url: 'https://example.org/private', content: 'private',
    }, 'travel');
    expect(context).toMatchObject({ version: 1, kind: 'travel_connection', description: 'Direct  train  & seat reservation',
      starts_at: '2027-03-20T07:00:00.000Z', ends_at: '2027-03-20T15:00:00.000Z',
      timezone: 'Europe/Berlin', location: 'Berlin Hbf', app_id: 'travel' });
    expect(context.facts).toContainEqual({ label: 'Provider', value: 'Rail provider' });
    expect(context).not.toHaveProperty('messages');
    expect(JSON.stringify(context)).not.toContain('example.org');
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
  it('bounds every field, omits invalid dates/zones and never serializes nested source objects', () => {
    const context = buildReminderNotificationContext('health_appointment', '😀'.repeat(300), {
      description: 'x'.repeat(3000), summary: 's'.repeat(900), icon: 'i'.repeat(90), category: 'c'.repeat(90),
      location: 'a'.repeat(2000), provider: 'p'.repeat(900), date_start: 'invalid', timezone: 'invalid',
      origin: { secret: true },
    }, 'a'.repeat(100));
    expect(Array.from(context.title)).toHaveLength(200);
    expect(context.description).toHaveLength(2000);
    expect(context.summary).toHaveLength(500);
    expect(context.icon).toHaveLength(64);
    expect(context.category).toHaveLength(64);
    expect(context.app_id).toHaveLength(64);
    expect(context.location).toHaveLength(1000);
    expect(context.facts).toEqual([{ label: 'Provider', value: 'p'.repeat(512) }]);
    expect(context.kind).toBe('appointment');
    expect(context).not.toHaveProperty('starts_at');
    expect(context).not.toHaveProperty('timezone');
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
  it('retains displayed chat title, summary, icon and category without the chat itself', () => {
    expect(buildReminderNotificationContext('chat', 'My itinerary', {
      summary: 'A weekend trip', icon: 'Train', category: 'travel', messages: ['private'],
    })).toEqual({ version: 1, kind: 'chat', title: 'My itinerary', summary: 'A weekend trip', icon: 'Train', category: 'travel' });
  });
});

describe('optional reminder thumbnails', () => {
  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
  it('fits multi-byte metadata within the server UTF-8 budget while preserving description', () => {
    const context = buildReminderNotificationContext('event', '旅'.repeat(200), {
      description: '描'.repeat(2000), summary: '要'.repeat(500), location: '所'.repeat(1000),
      provider: '供'.repeat(512), origin: '発'.repeat(512), destination: '着'.repeat(512),
      transport_method: '鉄'.repeat(512), price: '金'.repeat(512), duration: '時'.repeat(512),
      property_type: '宿'.repeat(512), speciality: '医'.repeat(512),
    });
    // Python's json.dumps adds whitespace around separators; conservative padding
    // confirms the compact browser encoding still fits that representation.
    expect(new TextEncoder().encode(JSON.stringify(context)).length + 300).toBeLessThanOrEqual(8192);
    expect(context.description).toBe('描'.repeat(2000));
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
  it('loads through the image proxy once and emits bounded JPEG bytes at <=600px', async () => {
    const fetchImage = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['image'], { type: 'image/png' }) });
    vi.stubGlobal('fetch', fetchImage);
    const close = vi.fn();
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1200, height: 800, close }));
    const drawImage = vi.fn();
    const canvas = { width: 0, height: 0, getContext: () => ({ fillRect: vi.fn(), drawImage, fillStyle: '' }),
      toDataURL: vi.fn().mockReturnValue('data:image/jpeg;base64,aGVsbG8=') };
    vi.spyOn(document, 'createElement').mockReturnValue(canvas as unknown as HTMLCanvasElement);
    expect(await captureReminderThumbnail('https://example.org/photo.png')).toBe('aGVsbG8=');
    expect(fetchImage).toHaveBeenCalledOnce();
    expect(fetchImage.mock.calls[0][0]).toBe('/proxy?url=https%3A%2F%2Fexample.org%2Fphoto.png&max_width=520');
    expect(canvas.width).toBe(600);
    expect(canvas.height).toBe(400);
    expect(drawImage).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
  it('omits unsafe URLs and failed image requests without affecting metadata', async () => {
    const fetchImage = vi.fn().mockRejectedValue(new Error('Unavailable'));
    vi.stubGlobal('fetch', fetchImage);
    vi.stubGlobal('createImageBitmap', vi.fn());
    for (const url of ['data:image/png;base64,AAAA', 'file:///tmp/a.png', '//example.org/a.png', '/\\example.org/a.png']) {
      expect(await captureReminderThumbnail(url)).toBeUndefined();
    }
    expect(fetchImage).not.toHaveBeenCalled();
    expect(await captureReminderThumbnail('/existing-thumbnail.png')).toBeUndefined();
    expect(fetchImage).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
  it('omits image output that exceeds the base64 budget at every quality', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['image'], { type: 'image/jpeg' }) }));
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 100, height: 100, close: vi.fn() }));
    const canvas = { getContext: () => ({ fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: '' }),
      toDataURL: vi.fn().mockReturnValue(`data:image/jpeg;base64,${'a'.repeat(160 * 1024 + 1)}`) };
    vi.spyOn(document, 'createElement').mockReturnValue(canvas as unknown as HTMLCanvasElement);
    expect(await captureReminderThumbnail('https://example.org/large.jpg')).toBeUndefined();
    expect(canvas.toDataURL).toHaveBeenCalledTimes(3);
  });
});
