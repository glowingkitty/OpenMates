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

from skills.news.rss.get_rss_highlights import get_rss_highlights
from skills.news.get_systemprompt import get_systemprompt
from skills.intelligence.ask_llm import ask_llm

import json
from datetime import datetime
import asyncio


def get_news_video_outline(use_existing_file_if_exists: bool = True):
    try:
        add_to_log(state="start", module_name="News Update", color="cyan")
        add_to_log(f"Start getting news video script ...")

        # based on the news highlights, generate a video script
        news_as_json = None
        current_date = datetime.now().strftime("%Y_%m_%d")
        folder_path = f"{main_directory}/temp_data/rss/{current_date}"
        news_highlights_filename = f"{folder_path}/news_filtered_for_highlights_{current_date}.json"
        news_video_script_filename = f"{folder_path}/news_video_script_{current_date}.json"
        os.makedirs(folder_path, exist_ok=True)

        # check if the file already exists, if so, return it
        if use_existing_file_if_exists and os.path.exists(news_video_script_filename):
            add_to_log(f"\U00002714 Using existing file: news_video_script_{current_date}.json")
            with open(news_video_script_filename, "r") as f:
                return json.load(f)

        if use_existing_file_if_exists:
            if os.path.exists(news_highlights_filename):
                add_to_log(f"\U00002714 Using existing file: news_filtered_for_highlights_{current_date}.json")
                with open(news_highlights_filename, "r") as f:
                    news_as_json = json.load(f)

        # get the systemprompt
        systemprompt = get_systemprompt(purpose="video_script")

        # get the news
        if not news_as_json:
            news_as_json = get_rss_highlights(
                use_existing_file_if_exists=use_existing_file_if_exists,
                save_as_json=True,
                return_content="json"
                )
            if not news_as_json:
                return None

        # prepare message history for LLM
        message_history = [
            {"role": "system", "content":systemprompt},
            {"role": "user", "content":str(news_as_json)}
        ]

        # send to LLM and get video script as json
        response = asyncio.run(ask_llm(
            message_history=message_history,
            model="gpt-4-turbo-preview",
            response_format="json")
        )
        clips = response["clips"]

        video_script = {
            "name": f"Daily News Update {current_date}",
            "background_music": {
                "file": "bensound_com_elevate.mp3",
                "duration": "full"
            },
            "clips": clips,
        }

        # then save the response to a file
        with open(news_video_script_filename, "w") as f:
            json.dump(video_script, f, indent=4)
        
        return video_script

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"While getting the news video script", traceback=traceback.format_exc())


if __name__ == "__main__":
    get_news_video_outline(use_existing_file_if_exists=True)