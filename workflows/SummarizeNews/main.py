import sys
import os
import re
import traceback

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from skills.news.send_video_summary_to_chat import send_video_summary_to_chat


def process():
    send_video_summary_to_chat()