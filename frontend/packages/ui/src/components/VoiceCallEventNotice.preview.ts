const defaults = { event: { schema_version: 1, type: 'voice_call', action: 'started',
  call_id: 'call-preview-1234', created_at: Date.UTC(2026, 9, 15, 12, 31) / 1000, active_elapsed_seconds: 0 } };
export default defaults;
export const variants = {
  ended: { event: { ...defaults.event, action: 'ended',
    created_at: Date.UTC(2026, 9, 15, 12, 33) / 1000, active_elapsed_seconds: 120 } },
};
