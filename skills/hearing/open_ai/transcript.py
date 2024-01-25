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

from skills.hearing.open_ai.get_costs_transcript import get_costs_transcript
from skills.hearing.open_ai.post_to_api_usage_transcript import post_to_api_usage_transcript

import time
from pydub import AudioSegment
from pydub.utils import mediainfo
from openai import OpenAI

# follow instructions https://platform.openai.com/docs/api-reference/audio/createTranscription


def transcript(
        audio_file_path: str,
        model_name: str = "whisper-1") -> str:
    try:
        add_to_log(state="start", module_name="OpenAI", color="yellow")
        add_to_log("Start transcribing the audio file ...")

        # check if the audio file exists
        if not os.path.isfile(audio_file_path):
            raise FileNotFoundError(f"The audio file {audio_file_path} does not exist.")
        
        # get the length of the audio file
        audio_file_info = mediainfo(audio_file_path)
        seconds_of_audio = int(float(audio_file_info["duration"]))

        # load the config
        secrets = load_secrets()
        config = load_config()
        client = OpenAI(api_key=secrets["OPENAI_API_KEY"])

        # get the predicted costs of the transcription
        costs = get_costs_transcript(seconds_of_audio=seconds_of_audio, model_name=model_name)
        if not costs:
            add_to_log(f"Failed to get the costs of the transcription. Aborting transcription...")
            return None

        # warn about the costs in log
        add_to_log(f"You are about to spend {round(costs['total_costs'],4)} {costs['currency']} for transcribing the {seconds_of_audio} seconds of audio file using the {model_name} model.")
        
        if config["environment"] == "development":
            add_to_log("Press CTRL+C to cancel or wait 5 seconds to auto continue ...")
            time.sleep(5)

        # get ready to transcribe the audio file
        transcription = ""
        audio_parts = []

        # load the audio file
        audio = AudioSegment.from_file(audio_file_path)

        # check if the audio is longer than 5 minutes, if so, split it into 5 minute parts
        per_part_duration_minutes = 5
        if len(audio) > per_part_duration_minutes * 60 * 1000:  # duration is in milliseconds
            for i in range(0, len(audio), per_part_duration_minutes * 60 * 1000):
                part = audio[i:i + per_part_duration_minutes * 60 * 1000]
                audio_parts.append(part)
        else:
            audio_parts.append(audio)

        # for each audio part, transcribe it and add the transcription to the final transcription
        for part in audio_parts:
            # save the part as a temporary file
            temp_file_path = "temp.wav"
            part.export(temp_file_path, format="wav")

            with open(temp_file_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
                transcription += transcript

            # delete the temporary file
            os.remove(temp_file_path)

            # calculate the duration of the part in seconds
            part_duration_seconds = len(part) / 1000  # len(part) gives duration in milliseconds

            # post to API usage transcript for each part
            post_to_api_usage_transcript(seconds_of_audio=part_duration_seconds, model_name=model_name)


        add_to_log("Successfully transcribed the audio file.", state="success")

        return transcription
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to transcribe the audio file", traceback=traceback.format_exc())
        return None
    

# Test the function
if __name__ == "__main__":
    current_directory = os.path.dirname(os.path.realpath(__file__))
    file_name = "test.m4a"
    # change from folder 'functions/...' to 'functions/transcript/'
    transcript_folder = re.sub('transcript.*', 'transcript', current_directory)
    audio_file_path = os.path.join(transcript_folder, file_name)
    transcript_text = transcript(audio_file_path=audio_file_path)
    print(transcript_text)