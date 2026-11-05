// App-wide spoken-word progress for the live call's current reply.
import { assistantSpeechController } from './assistantSpeechController';
import { voiceCallController } from './voiceCall';
import { createVoiceCallSpokenProgress } from './voiceCallSpokenProgress';

export const voiceCallSpokenProgress = createVoiceCallSpokenProgress(voiceCallController, assistantSpeechController);
