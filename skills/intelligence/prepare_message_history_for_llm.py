import traceback
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('API_OpenAI.*', '', full_current_path)
sys.path.append(main_directory)

from skills.web_browsing.convert_website_and_pdf_to_text import convert_website_and_pdf_to_text
from skills.pdf.pdf_to_text import pdf_to_text
from server.api.endpoints.skills.youtube.get_transcript import get_transcript_processing
from skills.youtube.get_video_details import get_video_details
from chat.mattermost.functions.file.get_file import get_file
from skills.vision.open_ai.prepare_image import prepare_image
from skills.video.video_to_images_and_text import video_to_images_and_text
import shutil
import copy
import json

from server import *

def detect_filepaths(input_string):
    words = input_string.split()
    filepaths = [word for word in words if os.path.isfile(word)]
    return filepaths

# inputs a list of messages and outputs a list in the format that ChatGPT expects
def prepare_message_history_for_llm(
        message_history: list,
        bot: dict,
        channel_name: str,
        allow_image_processing: bool = True) -> dict["model": bool, "message_history": list]:
    try:
        add_to_log(state="start", module_name="LLMs", color="yellow")
        add_to_log("Preparing message history for LLM (large language model) ...")

        # TODO: if channel_name is accounting and there is a PDF file in the most recent message of the history
        # and in the message history there is a message with “Date/Time” and “Bank account” and “Amount” field and “Payment purpose” fields
        # then process the message differently, by processing pdf file with add_voucher pipeline (return dict with 'start_skill')

        secrets = load_secrets()
        config = load_config()

        added_images = False

        # get the model for the bot_name
        model = bot["model"]
        model_can_process_images = True if "gpt-4" in bot["model"] else False

        # initialize list
        message_history_chatgpt = []

        # message_history = [
        #         {"role": "user", "content":new_message},
        #         {"role": "assistant", "content":system_prompt},
        #         ]

        # iterate over messages
        new_messages = []
        if message_history:
            for message in message_history:
                # I have no idea why this code exists to be honest... will comment it out for now and hope it doesn't break stuff
                # # also make the code work if the structure is in the format of chatgpt
                # if message.get("role") and message.get("content"):
                #     message["message_by_user_name"] = message["role"]
                #     message["message"] = message["content"]
                
                if message.get("message_by_user_name") and message.get("message"):
                    message["role"] = "assistant" if message["message_by_user_name"] == bot["user_name"] else "user"
                    message["content"] = message["message"]

                # if the message is from bot_name, set role to assistant
                # else role is user
                if message.get("message_by_user_name") == bot["user_name"] or message.get("role") == "assistant":
                    role = "assistant"
                else:
                    role = "user"

                text_message = message["message"] if message.get("message") else message["content"]

                # replace all website urls with content from website
                # example "Take a look at this website: https://www.adafruit.com/product/4681"
                # -> "Take a look at this website: https://www.adafruit.com/product/4681 (Website content: WEBSITE START {website content} WEBSITE END})"
                # find the website urls first
                website_urls = re.findall(r'(https?://\S+)', text_message)
                local_filepaths = detect_filepaths(text_message)
                images = []

                # process all local files
                if allow_image_processing and model_can_process_images and local_filepaths:
                    for filepath in local_filepaths:
                        # check if file is 'type'=='image/jpeg' or 'type'=='image/png'
                        if filepath.endswith(('.png', '.jpg', '.jpeg')):
                            # prepare the image
                            image = prepare_image(input_file_path=filepath)
                            # add the image to the list of images
                            images.append(image)
                            text_message = text_message.replace(filepath, f'(Image {len(images)})')
                            added_images = True

                        elif is_text_based(filepath):
                            # add text based files to the message history, like pdfs, txt files, .json, .py , etc.
                            with open(filepath, 'rb') as file:
                                file_content = file.read().decode('utf-8')
                            text_message+=f"\n\n{os.path.basename(filepath)}:\n{file_content}"

                        elif filepath.endswith('.pdf'):
                            # OCR pdf and add to the message history
                            with open(filepath, 'rb') as file:
                                file_content = file.read()
                            pdf_text = pdf_to_text(file_content=file_content)
                            text_message+=f"\n\n{os.path.basename(filepath)}:\n{pdf_text}"


                # process all attached images
                if allow_image_processing and model_can_process_images and message.get("attached_files"):
                    for file in message["attached_files"]:
                        try:
                            # check if file is 'type'=='image/jpeg' or 'type'=='image/png'
                            if file["type"] == "image/jpeg" or file["type"] == "image/png":
                                # get the image
                                image = get_file(file_id=file["id"])
                                # process the image
                                image = prepare_image(image_bytes=image)
                                # add the image to the list of images
                                images.append(image)
                                added_images = True

                            # check if the file is a video, if so process it with the video_to_images_and_text function
                            elif file["type"] == "video/mp4" or file["type"] == "video/quicktime":
                                added_images = True
                                model = "gpt-4-vision-preview"

                                video = get_file(file_id=file["id"])
                                # creat a new temp folder for the video
                                filename_without_extension = os.path.splitext(file["name"])[0]
                                videofolderpath = os.path.join(main_directory, "temp_data/video_to_images_and_text", filename_without_extension)
                                if not os.path.exists(videofolderpath):
                                    os.makedirs(videofolderpath)
                                # save the video to the temp folder
                                videofilepath = os.path.join(videofolderpath, file["name"])
                                with open(videofilepath, "wb") as f:
                                    f.write(video)
                                    
                                video_details = video_to_images_and_text(filepath=videofilepath)
                                # for every clip in the video, add a new message to the message history, with all the screenshots and the transcript for that clip
                                for clip in video_details["clips"]:
                                    video_screenshots = []
                                    # process each screenshot image
                                    for screenshot in clip["screenshots"]:
                                        image = prepare_image(input_file_path=screenshot)
                                        video_screenshots.append(image)
                                    
                                    # create a new message for each clip
                                    new_messages.append((message_history.index(message) + 1, {"role": role, "content": [
                                        {
                                            "type": "text",
                                            "text": clip["transcript"]
                                        },
                                        *[
                                            {
                                                "type": "image_url",
                                                "image_url": {"url": f"data:image/jpeg;base64,{screenshot}"}
                                            }
                                            for screenshot in video_screenshots
                                        ]
                                    ]}))

                                # once the photos and json of the video are processed, delete the folder with them
                                shutil.rmtree(videofolderpath)


                            elif is_text_based(file['type']):
                                # add text based files to the message history, like pdfs, txt files, .json, .py , etc.
                                file_content = get_file(file_id=file["id"])
                                text_message+=f"\n\n{file['name']}:\n{file_content}"

                            elif file["type"] == "application/pdf":
                                # OCR pdf and add to the message history
                                file_content = get_file(file_id=file["id"])
                                pdf_text = pdf_to_text(file_content=file_content)
                                text_message+=f"\n\n{file['name']}:\n{pdf_text}"


                        except Exception:
                            process_error(
                                file_name=os.path.basename(__file__),
                                when_did_error_occure="While processing attached files",
                                traceback=traceback.format_exc(),
                                file_path=full_current_path,
                                local_variables=locals(),
                                global_variables=globals()
                            )

                # for each website url, get the content of the website
                for website_url in website_urls:
                    # if the website is not from the chat server domain
                    if website_url.startswith(secrets["MATTERMOST_DOMAIN"]):
                        # TODO get the message history of the linked thread

                        pass
                    # detect image links and add them to gpt-4 vision
                    elif allow_image_processing and model_can_process_images and website_url.endswith(('.png', '.jpg', '.jpeg')):
                        # prepare the image
                        image = prepare_image(input_file_path=website_url)
                        # add the image to the list of images
                        images.append(image)
                        text_message = text_message.replace(website_url, f'(Image {len(images)})')

                    elif bot["user_name"] == "summer" and "youtube.com/watch?v=" in website_url:
                        video_details = get_video_details(website_url)
                        video_transcript = get_transcript(website_url)

                        # replace the website url with the website content
                        new_text = f'{website_url} (YouTube video details:\n'
                        new_text += f'Channel: {video_details["channel"]}\n'
                        new_text += f'Title: {video_details["title"]}\n'
                        new_text += f'Duration HH:MM:SS: {video_details["duration_h_m_s"]}\n'
                        new_text += f'Description: {video_details["description"]}\n'
                        new_text += f'Transcript:\nTRANSCRIPT START\n\n{video_transcript}\n\TRANSCRIPT END)' if video_transcript else ""
                        text_message = text_message.replace(website_url, new_text)
                        
                    elif bot["user_name"] == "summer":
                        # get the content of the website
                        website_details = convert_website_and_pdf_to_text(website_url)

                        # replace the website url with the website content and details
                        text_message = text_message.replace(website_url, website_details)

                
                usernames_to_replace = [bot["user_name"] for bot in config["active_bots"]]
                usernames_pattern = '|'.join(usernames_to_replace)
                text_message = re.sub(r'@(' + usernames_pattern + ')', '', text_message)

                if allow_image_processing and model_can_process_images and images:
                    model = "gpt-4-vision-preview"
                    # add message with images to history
                    message_history_chatgpt.append({"role": role, "content": [
                        {
                            "type": "text",
                            "text": text_message
                        },
                        *[
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image}"}
                            }
                            for image in images
                        ]
                    ]})
                else:
                    # add message to history
                    message_history_chatgpt.append({"role": role, "content": text_message})

            # add new messages to the message history (for example, if a video was processed)
            if new_messages:
                for position, new_message in sorted(new_messages, key=lambda x: x[0], reverse=True):
                    message_history_chatgpt.insert(position, new_message)

        # if the model is defined as "gpt-3.5", change it to "gpt-3.5-turbo"
        if model == "gpt-3.5":
            model = "gpt-3.5-turbo" 
        elif model == "gpt-4":
            model = "gpt-4-turbo-preview"


        # remove empty messages, for example:
        # {
        #     "role": "user",
        #     "content": " "
        # }
        message_history_chatgpt = [message for message in message_history_chatgpt if message["content"] != " "]
        filtered_message_history = [{'role': message['role'], 'content': message['content']} for message in message_history_chatgpt]

        response = {
            "model": model,
            "message_history": filtered_message_history,
            "includes_images": True if added_images else False
        }

        return response

    except Exception:
        process_error("Failed converting the message history to ChatGPT format", traceback=traceback.format_exc())

# Function to check if the file is text-based
def is_text_based(mime_type):
    main_type, _, _ = mime_type.partition(';')
    return main_type.startswith('text/') or main_type == 'application/json'