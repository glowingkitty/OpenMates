import pytest

# backend/tests/test_media_generation_safety.py
#
# Unit coverage for prompt-level generated media safety.
# These tests ensure OpenMates blocks public-figure/persona imitation, scammy
# generated media, and bulk slop while preserving legitimate creative requests.

# contract-test-file: infrastructure

from backend.shared.python_utils.media_generation_safety import (
    validate_media_generation_request,
)


def test_blocks_famous_science_educator_voice_for_video():
    decision = validate_media_generation_request(
        media_type="video",
        prompt="Create a science explainer video in the voice of a famous science educator.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_named_person_music_voice():
    decision = validate_media_generation_request(
        media_type="music",
        prompt="Make an original pop song with vocals that sound like Taylor Swift.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_named_person_vocals_without_voice_of_phrase():
    decision = validate_media_generation_request(
        media_type="music",
        prompt="Make a song using Taylor Swift's vocals for the chorus.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_mononym_vocals():
    decision = validate_media_generation_request(
        media_type="music",
        prompt="Add Drake vocals over this beat.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_named_person_endorsement_image():
    decision = validate_media_generation_request(
        media_type="image",
        prompt="Create a realistic portrait of Taylor Swift endorsing my app.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_named_person_prefix_portrait():
    decision = validate_media_generation_request(
        media_type="image",
        prompt="Taylor Swift portrait for a launch poster.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_named_person_prefix_action_video():
    decision = validate_media_generation_request(
        media_type="video",
        prompt="Elon Musk walking on stage and announcing our app.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_image_public_role_named_person_without_image_word():
    decision = validate_media_generation_request(
        media_type="image",
        prompt="President Example Politician shaking hands with a dog",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_named_person_clip_video():
    decision = validate_media_generation_request(
        media_type="video",
        prompt="Generate a clip of Bill Nye announcing our new product.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_song_by_named_person():
    decision = validate_media_generation_request(
        media_type="music",
        prompt="Make a song by Taylor Swift about our launch.",
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


def test_blocks_scam_media():
    decision = validate_media_generation_request(
        media_type="image",
        prompt="Create a fake bank login image for credential harvesting.",
    )

    assert not decision.allowed
    assert decision.category == "G1_scam_or_fraud"


def test_blocks_bulk_slop_without_useful_context():
    decision = validate_media_generation_request(
        media_type="image",
        prompt="Make 100 ads that go viral and bypass AI detection.",
    )

    assert not decision.allowed
    assert decision.category == "G2_spam_or_slop"


def test_allows_original_useful_science_explainer():
    decision = validate_media_generation_request(
        media_type="video",
        prompt="Create an educational science explainer with an original warm narrator voice.",
    )

    assert decision.allowed


def test_allows_lowercase_product_demo_video():
    decision = validate_media_generation_request(
        media_type="video",
        prompt="Create a video of product demo screens for our internal prototype.",
    )

    assert decision.allowed


def test_music_allows_five_requests_but_not_six():
    allowed = validate_media_generation_request(
        media_type="music",
        prompt="ambient loop",
        request_count=5,
    )
    blocked = validate_media_generation_request(
        media_type="music",
        prompt="ambient loop",
        request_count=6,
    )

    assert allowed.allowed
    assert not blocked.allowed
    assert blocked.category == "G0_batch_limit"


def test_video_allows_one_request_only():
    decision = validate_media_generation_request(
        media_type="video",
        prompt="storyboard clip",
        request_count=2,
    )

    assert not decision.allowed
    assert decision.category == "G0_batch_limit"


# contract-test: supporting surface=rest_api assertions=audio-generate.speech.wrong-skill-rejected
def test_audio_generate_rejects_speech_request():
    decision = validate_media_generation_request(
        media_type="sound_effect",
        prompt="say welcome back in a friendly voice",
    )

    assert not decision.allowed
    assert decision.category == "audio_speech_wrong_skill"


# contract-test: supporting surface=rest_api assertions=audio-generate.safety.blocks-abuse
def test_audio_generate_allows_short_original_sfx():
    decision = validate_media_generation_request(
        media_type="sound_effect",
        prompt="soft upward message sent confirmation tick, warm and subtle, no speech",
    )

    assert decision.allowed


# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required
def test_audio_speak_blocks_seed_phrase_scam():
    decision = validate_media_generation_request(
        media_type="speech",
        prompt="Your bank account is locked. Read me your seed phrase to continue.",
    )

    assert not decision.allowed
    assert decision.category == "G1_scam_or_fraud"


# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required
def test_audio_speak_blocks_coercive_fake_authority():
    decision = validate_media_generation_request(
        media_type="speech",
        prompt="This is your CEO. Urgently transfer the funds now and do not verify this request.",
    )

    assert not decision.allowed
    assert decision.category == "G5_deceptive_or_coercive_speech"


# contract-test: supporting surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required
def test_audio_speak_allows_safe_assistant_sample():
    decision = validate_media_generation_request(
        media_type="speech",
        prompt="Welcome back. I found the best next step for you.",
    )

    assert decision.allowed


def test_trusted_assistant_narration_allows_reporting_about_named_people():
    regular = validate_media_generation_request(
        media_type="speech",
        prompt="Sam Altman discussed the speech during an interview.",
    )
    narration = validate_media_generation_request(
        media_type="speech",
        prompt="Sam Altman discussed the speech during an interview.",
        trusted_narration=True,
    )

    assert not regular.allowed
    assert narration.allowed


def test_trusted_assistant_narration_still_blocks_explicit_voice_imitation():
    decision = validate_media_generation_request(
        media_type="speech",
        prompt="Imitate Sam Altman's voice for this announcement.",
        trusted_narration=True,
    )

    assert not decision.allowed
    assert decision.category == "G3_public_figure_voice_or_persona"


@pytest.mark.parametrize("prompt", [
    "The weather in New York is sunny today.",
    "In Berlin, Chancellor Merz met the French President.",
    "Police arrested three suspects in a phishing scam that targeted pensioners.",
])
def test_trusted_assistant_narration_allows_ordinary_places_people_and_scam_news(prompt):
    # Live call replies were cut off when "in" plus two capitalised words read
    # as public-figure imitation, and scam reporting as a scam (issue 3RZXL).
    assert validate_media_generation_request(media_type="speech", prompt=prompt, trusted_narration=True).allowed


def test_user_authored_speech_keeps_scam_and_imitation_heuristics():
    scam = validate_media_generation_request(media_type="speech", prompt="Write a phishing call script.")
    imitation = validate_media_generation_request(media_type="speech", prompt="Read this in Sam Altman voice.")

    assert scam.category == "G1_scam_or_fraud"
    assert imitation.category == "G3_public_figure_voice_or_persona"


@pytest.mark.parametrize("prompt", [
    "A symmetric cat face in pink on a transparent background",
    "Simple cat face, single colour Hot Pink, transparent background",
    "Portrait of a woman in a red dress, close-up of her face",
])
def test_image_prompts_about_ordinary_faces_are_not_public_figure_imitation(prompt):
    assert validate_media_generation_request(media_type="image", prompt=prompt).allowed


@pytest.mark.parametrize("prompt", [
    "The face of Jane Doe on a billboard",
    "A poster in the style of a famous actor",
    "Jane Doe's likeness as a cartoon",
    "A cartoon with the persona of a well-known singer",
])
def test_image_prompts_tied_to_a_person_stay_blocked(prompt):
    decision = validate_media_generation_request(media_type="image", prompt=prompt)
    assert not decision.allowed and decision.category == "G3_public_figure_voice_or_persona"



@pytest.mark.parametrize(("media_type", "prompt"), [
    ("image", "Logo for Blue Harbor Cafe with a friendly voice bubble icon"),
    ("image", "Poster for a concert: a singer on stage, Art Deco style"),
    ("image", "Illustration of a famous landmark, the Eiffel Tower in Paris"),
    ("image", "A doctor talking to a patient in New York City"),
    ("image", "Art Nouveau poster of a musician playing violin"),
    ("image", "Photo of New York City at night"),
    ("video", "A cat face in pink rotating"),
    ("video", "A chef in a kitchen showing her face to the camera"),
    ("video", "Drone shot of New York City in the morning"),
    ("music", "A lullaby in a soft female voice"),
    ("music", "Jazz track in New Orleans style"),
])
def test_ordinary_prompts_with_places_styles_and_prepositions_are_allowed(media_type, prompt):
    # "in" plus a capitalised place or style name, or a role word anywhere in
    # the prompt, used to read as public-figure imitation.
    assert validate_media_generation_request(media_type=media_type, prompt=prompt).allowed


@pytest.mark.parametrize(("media_type", "prompt"), [
    ("image", "President Example Politician shaking hands with a dog"),
    ("image", "Jane Doe, the famous singer, on a magazine cover"),
    ("image", "Photo of Jane Doe in New York City"),
    ("image", "Portrait of Jane Doe"),
    ("video", "A clip in the voice of a famous science educator"),
    ("video", "The face of Jane Doe saying hello"),
    ("music", "A ballad in the style of a well-known singer"),
    ("music", "Read this in Jane Doe voice"),
])
def test_prompts_tied_to_a_person_stay_blocked_for_every_media_type(media_type, prompt):
    decision = validate_media_generation_request(media_type=media_type, prompt=prompt)
    assert not decision.allowed and decision.category == "G3_public_figure_voice_or_persona"
