from youtube_transcript_api import YouTubeTranscriptApi
import os
import re
import sys

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *


def get_video_transcript(url: str, save_as_md=False) -> str:
    try:
        add_to_log(module_name="YouTube | Transcript", color="yellow", state="start")
        add_to_log(f"Getting transcript for video at URL: {url}")

        # Extract the video ID from the URL
        video_id = url.split("v=")[1]

        # Get the transcript for the video ID
        transcript = YouTubeTranscriptApi.get_transcript(video_id)

        # Concatenate the text values with timestamps
        transcript_text = ""
        for entry in transcript:
            start_time = entry['start']
            text = entry['text']
            transcript_text += f"[{format_time(start_time)}] {text}\n"

        # Save the transcript as a markdown file
        if save_as_md:
            text_filename = f"{main_directory}/temp_data/youtube_transcript/{video_id}.md"
            os.makedirs(os.path.dirname(text_filename), exist_ok=True)
            with open(text_filename, "w") as f:
                f.write(transcript_text)

        add_to_log(f"Got transcript for video at URL: {url}")

        # Return the transcript as a single string
        return transcript_text
    
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
    url = "https://www.youtube.com/watch?v=KtSabkVT8y4"
    transcript_text = get_video_transcript(url=url, save_as_md=True)
    
    # save as a markdown file
    text_filename = f"{main_directory}/temp_data/youtube_transcript/{url.split('v=')[1]}.md"
    os.makedirs(os.path.dirname(text_filename), exist_ok=True)

    with open(text_filename, "w") as f:
        f.write(transcript_text)

    subprocess.run(["code", text_filename])
