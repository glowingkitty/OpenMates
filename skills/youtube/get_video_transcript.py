from youtube_transcript_api import YouTubeTranscriptApi
import os
import re
import sys

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from skills.intelligence.costs.count_tokens import count_tokens

def get_video_transcript(url: str, save_as_md: bool=False, block_token_limit:int=None) -> list:
    try:
        add_to_log(module_name="YouTube | Transcript", color="yellow", state="start")
        add_to_log(f"Getting transcript for video at URL: {url}")

        # Extract the video ID from the URL
        video_id = url.split("v=")[1]

        # Get the transcript for the video ID
        transcript = YouTubeTranscriptApi.get_transcript(video_id)

        # Concatenate the text values with timestamps
        transcript_blocks = []
        block = ""
        token_count = 0
        for entry in transcript:
            start_time = entry['start']
            text = entry['text']
            text_tokens = count_tokens(text)
            if block_token_limit is not None and token_count + text_tokens > block_token_limit:
                transcript_blocks.append(block)
                block = f"[{format_time(start_time)}] {text}\n"
                token_count = text_tokens
            else:
                block += f"[{format_time(start_time)}] {text}\n"
                token_count += text_tokens
        if block:
            transcript_blocks.append(block)
        
        if save_as_md:
            transcript_text = "\n\n".join(transcript_blocks)

            # Save the transcript as a markdown file
            text_filename = f"{main_directory}/temp_data/youtube_transcript/{video_id}.md"
            os.makedirs(os.path.dirname(text_filename), exist_ok=True)
            with open(text_filename, "w") as f:
                f.write(transcript_text)

        add_to_log(f"Got transcript for video at URL: {url}", state="success")

        # Return the transcript as a list of blocks
        return transcript_blocks
    
    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to get the transcript for the video url '{url}'", traceback=traceback.format_exc())
        return None


def format_time(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"


if __name__ == "__main__":
    import subprocess
    import json
    url = "https://www.youtube.com/watch?v=30h5OlV_maw"
    transcript_blocks = get_video_transcript(url=url, save_as_md=True, block_token_limit=4000)
    text_filename = f"{main_directory}/temp_data/youtube_transcript/{url.split('v=')[1]}.md"
    json_filename = f"{main_directory}/temp_data/youtube_transcript/{url.split('v=')[1]}.json"

    # Save transcript_blocks as a JSON file
    with open(json_filename, 'w') as json_file:
        json.dump(transcript_blocks, json_file)

    # Open the markdown and json files
    subprocess.run(["code", text_filename])
    subprocess.run(["code", json_filename])