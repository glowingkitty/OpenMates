import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
from skills.all_skills import *
from skills.intelligence.openai.chat_complete import chat_complete
from skills.youtube.get_video_details import get_video_details
from skills.youtube.get_video_transcript import get_video_transcript


@skill_function(
    skill=YouTube(),
    function_name="Ask questions about a video.",
    function_icon="chat_questionmark",
    function_uses_other_functions_with_costs=[chat_complete] # NOTE Not sure if thats the best way to mark it
)
def ask_question_about_video(question: str, video_url: str) -> str:
    # first get the video details (title, description, channel, duration)
    details = get_video_details(video_url)

    # then get the transcript (and make sure the transcript is split into blocks of 4000 tokens max)
    transcript = get_video_transcript(video_url, block_token_limit=4000)

    # then ask the LLM to answer the question based on the details
    answer_based_on_details = chat_complete() #TODO

    # then, for each block of the transcript, ask the LLM to answer the question based on the block text
    answers_based_on_blocks = []
    for block in transcript:
        answer_based_on_block = chat_complete() #TODO
        answers_based_on_blocks.append(answer_based_on_block)

    # then, for all answers, ask the LLM to answer the question based on the answers
    answer_based_on_answers = chat_complete()
    
    return answer_based_on_answers



# metadata = read_metadata(ask_question_about_video)
# print(metadata)