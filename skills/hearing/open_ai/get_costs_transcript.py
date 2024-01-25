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

from pydub.utils import mediainfo


def get_costs_transcript(
        audio_file_path: str = None,
        seconds_of_audio: int = None,
        model_name: str = "whisper-1",
        currency: str = "USD") -> dict:
    try:
        add_to_log(state="start", module_name="OpenAI", color="yellow")

        # check if the audio file path or the minutes of audio are given
        if not audio_file_path and not seconds_of_audio:
            raise FileNotFoundError("Either the audio file path or the minutes of audio need to be given.")
        
        # check if the audio file path is given, if so, calculate the minutes of audio
        if audio_file_path:
            # check if the audio file exists
            if not os.path.isfile(audio_file_path):
                raise FileNotFoundError(f"The audio file {audio_file_path} does not exist.")
            
            audio_file_info = mediainfo(audio_file_path)
            seconds_of_audio = int(float(audio_file_info["duration"]))


        add_to_log(f"Calculating the costs using the {model_name} model...")
        prices_per_minute = {
            "whisper-1":0.006/60,
        }

        # calculate the costs
        total_costs = seconds_of_audio * prices_per_minute[model_name]

        add_to_log(state="success", message=f"Successfully calculated the costs for {seconds_of_audio} seconds of audio using the {model_name} model:")
        add_to_log(state="success", message=f"Total costs: {round(total_costs,4)} {currency}")
        return {
            "total_costs": total_costs,
            "currency": currency
            }
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed getting the costs for {seconds_of_audio} seconds of audio using the {model_name} model", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    # test the function with the arguments from the command line
    # tokens_used = int(sys.argv[1])

    current_directory = os.path.dirname(os.path.realpath(__file__))
    file_name = "test.m4a"
    # change from folder 'functions/...' to 'functions/transcript/'
    transcript_folder = re.sub('usage.*', 'transcript', current_directory)
    audio_file_path = os.path.join(transcript_folder, file_name)

    get_costs_transcript(
        audio_file_path=audio_file_path,
        # seconds_of_audio=tokens_used
    )