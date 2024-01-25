import traceback
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
current_directory = re.sub('news/.*', 'news', full_current_path)
sys.path.append(main_directory)

from server.message.get_location_time_date import get_location_time_date
from server.error.process_error import process_error
from server.logging.add_to_log import add_to_log
from server.shutdown.shutdown import shutdown


def get_systemprompt(purpose: str = "filter") -> str:
    try:
        add_to_log(module_name="News Update", color="cyan", state="start")
        add_to_log(f"Loading systemprompt for the purpose '{purpose}' ...")

        systemprompts_folder = re.sub('OpenMates.*', 'OpenMates/my_profile/systemprompts/special_usecases/daily_news_summary', full_current_path)

        # get the LLM systemprompt from .md files (include current date and time (AM/PM))
        location_time_date = get_location_time_date()

        with open(f"{systemprompts_folder}/systemprompt_base.md", "r") as f:
            base_prompt = f.read()

        location_time_date += "\n\n"+base_prompt

        if purpose == "filter":
            with open(f"{systemprompts_folder}/systemprompt_filter.md", "r") as f:
                filter_prompt = f.read()
            location_time_date += "\n\n"+filter_prompt
        elif purpose == "video_script":
            with open(f"{systemprompts_folder}/systemprompt_video_script.md", "r") as f:
                summarize_prompt = f.read()
            location_time_date += "\n\n"+summarize_prompt

        add_to_log(f"Successfully loaded systemprompt for the purpose '{purpose}'",state="success")

        return location_time_date
    
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to load systemprompt", traceback=traceback.format_exc())

if __name__ == "__main__":
    get_systemprompt(purpose="filter")