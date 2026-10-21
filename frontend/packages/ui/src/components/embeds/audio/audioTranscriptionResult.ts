/** Normalize the native batch skill envelope for the existing recording renderer. */
export function audioTranscriptionResultContent(content: Record<string, unknown>): Record<string, unknown> {
  if (content.app_id !== 'audio' || content.skill_id !== 'transcribe') return content;
  const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const input = record(content.input);
  const requests = Array.isArray(input.requests) ? input.requests.map(record) : [input];
  const transcripts: Record<string, unknown>[] = [];
  const collect = (value: unknown, depth = 0): void => {
    if (!value || depth > 4) return;
    if (Array.isArray(value)) { value.forEach(item => collect(item, depth + 1)); return; }
    const item = record(value);
    if (typeof item.transcript === 'string') transcripts.push(item);
    else if (Array.isArray(item.results)) collect(item.results, depth + 1);
  };
  collect(content);
  const first = transcripts[0] ?? {};
  const native = requests.find(item => item.s3_key === first.s3_key) ?? requests[0] ?? {};
  const s3Key = typeof first.s3_key === 'string' ? first.s3_key : native.s3_key;
  const duration = typeof first.duration_seconds === 'number' && first.duration_seconds >= 0
    ? `${Math.floor(first.duration_seconds / 60)}:${Math.floor(first.duration_seconds % 60).toString().padStart(2, '0')}` : content.duration;
  const joined = (field: string) => transcripts.length > 1 ? transcripts.map(item => {
    const title = typeof item.title === 'string' ? `${item.title}\n` : '';
    return title + String(item[field] ?? item.transcript ?? '');
  }).join('\n\n') : first[field];
  return { ...native, ...content, ...first, duration,
    transcript: joined('transcript') ?? content.transcript,
    transcript_original: joined('transcript_original'), transcript_corrected: joined('transcript_corrected'),
    ...(typeof s3Key === 'string' && !content.s3_files ? { s3_files: { original: { s3_key: s3Key } } } : {}) };
}
