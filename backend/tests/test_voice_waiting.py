import asyncio

from backend.apps.ai.assistant_speech.voice_waiting import DelayedVoiceWaiting


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_delayed_waiting_uses_request_language_once_and_never_falls_back_to_english():
    spoken = []
    waiting = DelayedVoiceWaiting(language="de-DE", response_ready=lambda: False,
                                  dispatch=spoken.append, delay_seconds=0.001)
    waiting.start()
    waiting.start()
    await asyncio.sleep(0.01)
    await waiting.close()
    assert spoken == ["Lass mich kurz darüber nachdenken."]
    unsupported = DelayedVoiceWaiting(language="zz", response_ready=lambda: False,
                                      dispatch=spoken.append, delay_seconds=0)
    unsupported.start()
    await asyncio.sleep(0)
    await unsupported.close()
    assert len(spoken) == 1


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_useful_response_or_completion_suppresses_waiting_confirmation():
    spoken = []
    ready = False
    waiting = DelayedVoiceWaiting(language="en", response_ready=lambda: ready,
                                  dispatch=spoken.append, delay_seconds=0.001)
    waiting.start()
    ready = True
    await asyncio.sleep(0.01)
    await waiting.close()
    cancelled = DelayedVoiceWaiting(language="en", response_ready=lambda: False,
                                    dispatch=spoken.append, delay_seconds=0.01)
    cancelled.start()
    await cancelled.close()
    await asyncio.sleep(0.02)
    assert spoken == []
