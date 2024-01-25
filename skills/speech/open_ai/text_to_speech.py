################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from skills.speech.open_ai.get_costs_text_to_speech import get_costs_text_to_speech
from skills.speech.open_ai.post_to_api_usage_text_to_speech import post_to_api_usage_text_to_speech

import time
import uuid
from openai import OpenAI


# follow instructions https://platform.openai.com/docs/api-reference/audio/createSpeech


def text_to_speech(
    input_text: str,
    voice: str = "echo",
    model: str = "tts-1",
    speech_file_path: str = None
    ) -> str:
    try:
        add_to_log(state="start", module_name="Audio | Speech | OpenAI", color="yellow")
        add_to_log("Prepare to conert text to speech ...")

        # load env config
        secrets = load_secrets()
        config = load_config()
        client = OpenAI(api_key=secrets["OPENAI_API_KEY"])

        # check if the speech file path is given, if not, create a unique id and create the path
        if not speech_file_path:
            unique_id = str(uuid.uuid4())
            speech_file_path = f"{main_directory}/temp_data/speech/temp_speech_{unique_id}.mp3"
            os.makedirs(os.path.dirname(speech_file_path), exist_ok=True)

        # get the predicted costs of the transcription
        costs = get_costs_text_to_speech(num_characters=len(input_text), model_name=model)
        if not costs:
            add_to_log("Faled to get the costs for the text to speech.")
            return None

        # warn about the costs in log
        add_to_log(f"You are about to spend {round(costs['total_costs'],4)} {costs['currency']} for converting the text to speech.")

        if config["environment"] == "development":
            add_to_log("Press CTRL+C to cancel or wait 5 seconds to auto continue ...")
            time.sleep(5)

        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=input_text)
        response.stream_to_file(speech_file_path)

        # post to API usage
        post_to_api_usage_text_to_speech(num_characters=len(input_text), model_name=model)

        add_to_log(f"Successfully converted text to speech. You can find the audio file here: {speech_file_path}")

        return speech_file_path


    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to convert text to speech", traceback=traceback.format_exc())
        return None


if __name__ == "__main__":
    text_to_speech("How are you doing today?")