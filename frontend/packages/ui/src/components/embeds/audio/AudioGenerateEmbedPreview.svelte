<!--
  frontend/packages/ui/src/components/embeds/audio/AudioGenerateEmbedPreview.svelte

  Preview wrapper for audio.generate and audio.speak app-skill embeds.
  Reuses the generated-audio player used by music.generate while preserving the
  audio app identity, icon, and stable audio-specific test IDs.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import MusicGenerateEmbedPreview from '../music/MusicGenerateEmbedPreview.svelte';
  import {
    getGeneratedAudioDataUrl,
    getGeneratedAudioFiles,
    getNumberField,
    getStringField,
    normalizeAudioSkillId,
    resolveGeneratedAudioContent,
    type GeneratedAudioFiles,
  } from './audioGeneratedEmbedContent';

  interface Props {
    id: string;
    skillId?: 'generate' | 'speak';
    content?: Record<string, unknown> | null;
    prompt?: string;
    textPreview?: string;
    generationType?: string;
    voice?: string;
    mode?: string;
    model?: string;
    durationSeconds?: number;
    s3BaseUrl?: string;
    files?: GeneratedAudioFiles;
    aesKey?: string;
    aesNonce?: string;
    previewAudioUrl?: string;
    status: 'processing' | 'finished' | 'error';
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    skillId = 'generate',
    content,
    prompt,
    textPreview,
    generationType,
    voice,
    mode,
    model,
    durationSeconds,
    s3BaseUrl,
    files,
    aesKey,
    aesNonce,
    previewAudioUrl,
    status,
    error,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  const sourceContent = $derived(resolveGeneratedAudioContent(content));
  const normalizedSkillId = $derived(normalizeAudioSkillId(skillId || sourceContent.skill_id));
  const skillName = $derived(
    normalizedSkillId === 'speak'
      ? $text('app_skills.audio.speak')
      : $text('app_skills.audio.generate')
  );
  const displayPrompt = $derived(
    prompt || textPreview || getStringField(sourceContent, ['prompt', 'text_preview'])
  );
  const displayMode = $derived(
    mode ||
      (normalizedSkillId === 'speak'
        ? voice || getStringField(sourceContent, ['voice'])
        : generationType || getStringField(sourceContent, ['generation_type'])) ||
      getStringField(sourceContent, ['mode']) ||
      (normalizedSkillId === 'speak' ? 'speech' : 'sound_effect')
  );
  const resolvedModel = $derived(model || getStringField(sourceContent, ['model']));
  const resolvedDurationSeconds = $derived(
    durationSeconds ?? getNumberField(sourceContent, ['duration_seconds'])
  );
  const resolvedS3BaseUrl = $derived(s3BaseUrl || getStringField(sourceContent, ['s3_base_url']));
  const resolvedFiles = $derived(files || getGeneratedAudioFiles(sourceContent));
  const resolvedAesKey = $derived(aesKey || getStringField(sourceContent, ['aes_key']));
  const resolvedAesNonce = $derived(aesNonce || getStringField(sourceContent, ['aes_nonce']));
  const resolvedPreviewAudioUrl = $derived(
    previewAudioUrl ||
      getStringField(sourceContent, ['previewAudioUrl', 'preview_audio_url', 'audio_url']) ||
      getGeneratedAudioDataUrl(sourceContent)
  );
  const coverSymbol = $derived(normalizedSkillId === 'speak' ? 'TTS' : 'SFX');
</script>

<MusicGenerateEmbedPreview
  {id}
  appId="audio"
  skillId={normalizedSkillId}
  {skillName}
  skillIconName="audio"
  prompt={displayPrompt}
  mode={displayMode}
  model={resolvedModel}
  modelFallbackName="ElevenLabs"
  durationSeconds={resolvedDurationSeconds}
  s3BaseUrl={resolvedS3BaseUrl}
  files={resolvedFiles}
  aesKey={resolvedAesKey}
  aesNonce={resolvedAesNonce}
  previewAudioUrl={resolvedPreviewAudioUrl}
  {status}
  {error}
  {taskId}
  {isMobile}
  {coverSymbol}
  accentColor="var(--color-app-audio)"
  processingStatusText={skillName}
  errorStatusText={error || skillName}
  testIdPrefix={`audio-${normalizedSkillId}`}
  {onFullscreen}
/>
