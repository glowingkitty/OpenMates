import { describe, expect, it } from 'vitest';
import { readAudioKinds, readVideoProgress, videoAudioStageText, videoChangeText, videoGenerateCardProps, videoMakerName, videoStageText } from '../videoGenerateCard';

const t = (key: string, options?: { values: Record<string, string> }) =>
  options ? `${key}(${Object.entries(options.values).map(([k, v]) => `${k}=${v}`).join(',')})` : key;

describe('videoGenerateCard helpers', () => {
  // contract-test: supporting surface=gui.web assertions=videos-generate.progress.shown-while-running
  it('reads the step, round and change of a processing update and keeps earlier values', () => {
    const first = readVideoProgress({ progress_stage: 'writing', progress_attempt: 1, change: 'edit', source_embed_id: 'video-1' });
    expect(first).toEqual({ stage: 'writing', attempt: 1, change: 'edit', sourceEmbedId: 'video-1' });
    expect(readVideoProgress({ progress_stage: 'correcting', progress_attempt: 2 }, first))
      .toEqual({ stage: 'correcting', attempt: 2, change: 'edit', sourceEmbedId: 'video-1' });
    expect(readVideoProgress({ progress_stage: 'unknown', change: 'shrink' }, first)).toEqual(first);
    expect(videoGenerateCardProps({ progress_stage: 'generating', change: 'extend_end', source_embed_id: 'v', author_model: 'a', made_by: 'composed' }))
      .toEqual({ authorModel: 'a', madeBy: 'composed', progressStage: 'generating', progressAttempt: undefined, change: 'extend_end', sourceEmbedId: 'v' });
  });

  // contract-test: supporting surface=gui.web assertions=videos-generate.progress.shown-while-running
  it('labels each step, the correction round and the kind of change', () => {
    expect(videoStageText({}, t)).toBeUndefined();
    expect(videoStageText({ stage: 'rendering', attempt: 1 }, t)).toBe('embeds.video_generate.progress_rendering');
    expect(videoStageText({ stage: 'correcting', attempt: 3 }, t)).toBe('embeds.video_generate.progress_correcting_round(round=3)');
    expect(videoChangeText('extend_start', t)).toBe('embeds.video_generate.change_extend_start');
    expect(videoChangeText(undefined, t)).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
  it('names the author model of a composed video and the video model of a generative one by display name', () => {
    expect(videoMakerName({ madeBy: 'composed', model: 'composed', authorModel: 'gpt-6.1-sol' })).toBe('GPT-6.1 Sol');
    expect(videoMakerName({ madeBy: 'composed', model: 'gpt-6.1-sol' })).toBe('GPT-6.1 Sol');
    expect(videoMakerName({ madeBy: 'generative', model: 'gemini-omni-1.2-flash' })).toBe('Gemini Omni 1.2 Flash');
    expect(videoMakerName({ madeBy: 'composed', model: 'composed' })).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=videos-generate.progress.shown-while-running
  it('names the sound being made from the kinds present', () => {
    expect(videoAudioStageText(['speech'], t)).toBe('embeds.video_generate.progress_audio_speech');
    expect(videoAudioStageText(['music'], t)).toBe('embeds.video_generate.progress_audio_music');
    expect(videoAudioStageText(['sound'], t)).toBe('embeds.video_generate.progress_audio_sound');
    expect(videoAudioStageText([], t)).toBe('embeds.video_generate.progress_audio_unknown');
    expect(videoAudioStageText(undefined, t)).toBe('embeds.video_generate.progress_audio_unknown');
    expect(videoAudioStageText(['music', 'speech'], t))
      .toBe('embeds.video_generate.progress_audio_several(kinds=embeds.video_generate.audio_list_and(head=embeds.video_generate.audio_noun_speech,last=embeds.video_generate.audio_noun_music))');
    expect(videoAudioStageText(['speech', 'sound', 'music'], t)).toContain('head=embeds.video_generate.audio_noun_speech, embeds.video_generate.audio_noun_sound');
  });

  // contract-test: supporting surface=gui.web assertions=videos-generate.progress.shown-while-running
  it('reads the audio kinds of a processing update, drops unknown kinds and keeps earlier kinds', () => {
    expect(readAudioKinds(['music', 'bogus', 'speech', 'speech'])).toEqual(['speech', 'music']);
    expect(readAudioKinds('speech')).toBeUndefined();
    const first = readVideoProgress({ progress_stage: 'audio', progress_audio: ['speech', 'sound'] });
    expect(first.stage).toBe('audio');
    expect(first.audio).toEqual(['speech', 'sound']);
    expect(readVideoProgress({ progress_stage: 'audio' }, first).audio).toEqual(['speech', 'sound']);
    expect(videoStageText(first, t)).toContain('progress_audio_several');
  });
});
