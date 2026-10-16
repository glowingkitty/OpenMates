/** Generation skills whose invocation may own multiple output embeds. */
export function isGeneratedMediaSkill(appId: unknown, skillId: unknown): boolean {
  if (typeof appId !== 'string' || typeof skillId !== 'string') return false;
  return (
    (appId === 'images' && ['generate', 'generate_draft', 'vectorize'].includes(skillId)) ||
    (appId === 'audio' && ['generate', 'speak'].includes(skillId)) ||
    (['music', 'videos', 'models3d'].includes(appId) && skillId === 'generate')
  );
}

/** Distinguish a generation invocation from a historical single-asset embed. */
export function isGeneratedMediaParent(
  appId: unknown,
  skillId: unknown,
  content: Record<string, unknown> | null | undefined,
): boolean {
  if (!isGeneratedMediaSkill(appId, skillId)) return false;
  if (content?.files || content?.previewImageUrl || content?.previewAudioUrl
      || content?.previewVideoUrl || content?.posterUrl || content?.modelUrl
      || content?.preview_image_url || content?.preview_audio_url
      || content?.preview_video_url || content?.poster_url || content?.model_url
      || content?.s3_base_url) return false;
  if (Array.isArray(content?.embed_ids)) return true;
  // Earlier single-output records placed the asset on app_skill_use itself.
  // Processing placeholders have no asset and should open the group shell.
  return true;
}

export function generatedMediaChildIds(content: Record<string, unknown> | null | undefined): string[] {
  const ids = content?.embed_ids;
  return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === 'string' && id.length > 0) : [];
}
