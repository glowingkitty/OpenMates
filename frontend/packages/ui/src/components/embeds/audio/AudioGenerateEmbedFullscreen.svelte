<!--
  frontend/packages/ui/src/components/embeds/audio/AudioGenerateEmbedFullscreen.svelte

  Fullscreen wrapper for audio.generate and audio.speak app-skill embeds.
  Normalizes audio-specific fields into the shared generated-audio player data
  shape so encrypted SFX and TTS results use the same playback path.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import MusicGenerateEmbedFullscreen from '../music/MusicGenerateEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    getGeneratedAudioDataUrl,
    getGeneratedAudioFiles,
    getNumberField,
    getStringField,
    normalizeAudioSkillId,
    resolveGeneratedAudioContent,
  } from './audioGeneratedEmbedContent';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  const decodedContent = $derived(resolveGeneratedAudioContent(data.decodedContent ?? {}));
  const normalizedSkillId = $derived(normalizeAudioSkillId(decodedContent.skill_id));
  const skillName = $derived(
    normalizedSkillId === 'speak'
      ? $text('app_skills.audio.speak')
      : $text('app_skills.audio.generate')
  );
  const displayPrompt = $derived(
    getStringField(decodedContent, ['prompt', 'text_preview'])
  );
  const displayMode = $derived(
    getStringField(decodedContent, [
      'mode',
      normalizedSkillId === 'speak' ? 'voice' : 'generation_type',
    ]) || (normalizedSkillId === 'speak' ? 'speech' : 'sound_effect')
  );
  const displayData = $derived({
    ...data,
    decodedContent: {
      ...decodedContent,
      app_id: 'audio',
      skill_id: normalizedSkillId,
      prompt: displayPrompt,
      mode: displayMode,
      duration_seconds: getNumberField(decodedContent, ['duration_seconds']),
      s3_base_url: getStringField(decodedContent, ['s3_base_url']),
      files: getGeneratedAudioFiles(decodedContent),
      aes_key: getStringField(decodedContent, ['aes_key']),
      aes_nonce: getStringField(decodedContent, ['aes_nonce']),
      previewAudioUrl:
        getStringField(decodedContent, ['previewAudioUrl', 'preview_audio_url', 'audio_url']) ||
        getGeneratedAudioDataUrl(decodedContent),
    },
  } as EmbedFullscreenRawData);
  const coverSymbol = $derived(normalizedSkillId === 'speak' ? 'TTS' : 'SFX');
</script>

<MusicGenerateEmbedFullscreen
  data={displayData}
  {onClose}
  {embedId}
  appId="audio"
  skillId={normalizedSkillId}
  {skillName}
  skillIconName="audio"
  modelFallbackName="ElevenLabs"
  {coverSymbol}
  accentColor="var(--color-app-audio)"
  testIdPrefix={`audio-${normalizedSkillId}`}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
/>
