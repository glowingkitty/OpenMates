# Voice calls

Start a voice call with the phone button in the chat action row. In an existing
chat it appears beside Close; on the new-chat workspace it creates a chat for
the conversation. Calls currently use Google Gemini Live and require a signed-in
account with enough credits.

Wait until the call shows Listening before speaking. Your speech and the
assistant's replies appear as ordinary chat messages. Submitted text, including
pasted text, reaches the same voice conversation. Both sides of the transcript
are encrypted in your browser before synchronization and remain available when
you return to the chat. Call transcripts do not start a separate text response.

Use the call's Mute control to stop microphone transmission and Hang up to end
the call. Composer audio recording is unavailable while the call owns the
microphone. Separate assistant speech is paused during a call. Closing the chat
or browsing another workspace keeps the call bound to its original chat; compact
controls let you return or hang up.

The controls show elapsed time and usage. The credits-per-minute figure is an
estimate; actual charges use the provider's reported token usage, including
conversation context. Authorization or connection failure visibly ends the call.
Transcript text is retained locally encrypted when synchronization needs recovery;
an unsuccessful save is not presented as confirmed server storage.

Raw microphone audio, submitted call text and permitted conversation context
are sent through OpenMates to Google. Raw call audio and its transcription do not
receive the personal-data placeholder substitution used for eligible text-chat
inference. The initial implementation does not save an audio recording.

The [calling Plan](../plans/integrated-voice-video-calling/plan.yml) defines three
increments: voice and text foundation; app skills, submitted files and embeds;
then camera/screen input and generated video. File interpretation, app skills,
video and team calls are unavailable in the foundation increment. Unsupported
attachment submissions preserve your draft.
