# Voice calls

Start a voice call with the phone button in the chat action row. In an existing
chat it appears beside Close; on the new-chat workspace it creates a chat for
the conversation. Calls currently use Google Gemini Live and require a signed-in
account with enough credits.

Before your first call, read the privacy notice and choose Continue. Google processes
your voice and the conversation context shared with the call. Google states that
paid Gemini API data is not used to train its models; limited safety logging can
still apply. The notice links [Google's current API terms](https://ai.google.dev/gemini-api/terms#paid-services).
Your acknowledgment is saved to your OpenMates profile, so later calls on your
other devices do not show it again. Canceling leaves the call unopened. If the
profile cannot be checked or saved, retry before starting the call.

Once the notice is accepted, you can start speaking after pressing Call; microphone audio is buffered while
the connection is prepared. Your speech and the
assistant's replies appear as ordinary chat messages. Submitted text, including
pasted text, reaches the same voice conversation. Both sides of the transcript
are encrypted in your browser before synchronization and remain available when
you return to the chat. Call transcripts do not start a separate text response. Spoken transcripts show no
generic sending or processing footer. Text you submit shows Sending until accepted.

Calls follow the same OpenMates ethics as text conversations. When you continue
a compressed chat, its saved summary and newer messages provide the context,
along with the chat's active focus. Long calls refresh that shared summary from
completed transcript turns. An assistant without a Mate category appears as
OpenMates with the OpenMates logo.

Ask to use an app in speech or in a submitted text message. OpenMates selects
relevant capabilities with Jev. Relevant memories and focus modes use the usual
sharing and activation controls, with their normal chat indicators. Requests
needing app skills use Gemini Flash for tool arguments and the ordinary skill
execution path; results appear as chat embeds while Gemini Live explains them
conversationally. Project context remains subject to its normal access decision.
Long-running app actions show their usual progress embeds and can finish after
you hang up. Their results remain in the original chat and use the app's usual
credits.

Use the round microphone button over the audio bars to mute or unmute. Its red
microphone-off icon means muted: background noise cannot interrupt the assistant,
and the call stays connected. Use the red downward handset to hang up. Composer audio recording is unavailable while the call owns the
microphone. Separate assistant speech is paused during a call. Closing the chat
or browsing another workspace keeps the call bound to its original chat.
Brief distinct sounds confirm connection, manual mute, manual unmute and call end;
automatic silence idle/resume remains quiet.

The blue call strip sits below the full chat header. As you scroll past the
header, it stays at the top with More before the video button and Close beside
Hang up. More contains the chat's report, share and other actions. Video currently
shows Coming soon. Closing the chat leaves a gently pulsing handset-and-timer
pill beside the main menu in place of the OpenMates brand. Press the pill to
return to the call's chat and restore the brand. Call start and end times appear
as encrypted system events in that chat's history.

Local speech detection loads in the background without delaying the call. Once
it is ready, five seconds of silence pauses microphone uploads while keeping the
call connected. Speaking resumes uploads automatically, including a short
buffer of preceding audio to preserve the start of your words. Manual Mute
always takes priority: use Unmute before speaking again. If detection cannot
load or keep up, the call continues streaming while unmuted.

The center shows real microphone or assistant-playback audio bars and active
duration. When the server confirms that both input and processing are idle, the
counter stops and fades smoothly. It resumes when streaming or processing
resumes. Already generated audio can continue playing while the counter is
paused. Mute, connection progress and errors remain accessible; the strip does
not show credit totals or a speak-to-resume hint.

Call information explains usage-based billing. Charges
use Gemini's reported token usage, including microphone audio, generated replies,
transcriptions and conversation context processed again on later turns. There is
no separate fee for keeping the connection open. Microphone uploads include
silence until automatic idle pauses them, and Gemini bills that streamed input.
Muting also pauses microphone transmission; assistant responses and submitted
text can still incur charges. Active duration describes listening and processing
activity; it is not a price per minute or a replacement for token-based billing.
Authorization or connection failure visibly ends the call.
Transcript text is retained locally encrypted when synchronization needs recovery;
an unsuccessful save is not presented as confirmed server storage.

See [Google's Live API billing guide](https://ai.google.dev/gemini-api/docs/live-api/best-practices#pricing-and-billing)
for the provider's token, context and proactive-audio billing rules.

Raw microphone audio, submitted call text and permitted conversation context
are sent through OpenMates to Google. Raw call audio and its transcription do not
receive the personal-data placeholder substitution used for eligible text-chat
inference. The initial implementation does not save an audio recording.

The [calling Plan](../plans/integrated-voice-video-calling/plan.yml) defines three
increments: voice and text foundation; app skills, submitted files and embeds;
then camera/screen input and generated video. Submitted-file interpretation,
video and team calls remain future increments. Attachments and explicit app
selections from the composer preserve your draft; request app capabilities in
your message instead.
