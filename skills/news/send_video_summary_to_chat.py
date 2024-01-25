import traceback
import sys
import os
import re
import datetime
import json
import requests

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error
from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.channel.get_channel_id import get_channel_id
from skills.news.video.get_video_summary import get_video_summary


def send_message(channel_id: str, message: str, headers: dict, posturl: str, file_ids=None):
    data = {
        "channel_id": channel_id,
        "message": message
    }
    if file_ids:
        data["file_ids"] = file_ids

    response = requests.post(posturl, headers=headers, data=json.dumps(data))
    if response.status_code != 201:
        raise Exception(f"Failed to send message: {response.content}")
    

def send_video_summary_to_chat():
    try:
        print("Sending video summary to chat...")
        # get the video summary
        video_message_file_path = get_video_summary(use_existing_file_if_exists=True)

        # upload the video summary to chat server
        current_date = datetime.datetime.now().strftime("%Y_%m_%d")
        folder_path = f"{main_directory}/temp_data/rss/{current_date}"
        highlights_json_path = f"{folder_path}/news_filtered_for_highlights_{current_date}.json"
        channel_name = "daily updates"

        secrets = load_secrets()
        bot_token = secrets["bots"]["api_keys"]["mattermost_access_token_burton"]
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        uploadurl = f"{mattermost_domain}/api/v4/files"
        posturl = f"{mattermost_domain}/api/v4/posts"
        channel_id = get_channel_id(channel_name=channel_name)
        headers = {
            'Authorization': f'Bearer {bot_token}',
            'Content-Type': 'application/json'
            }
        
        # load json
        with open(highlights_json_path, "r") as f:
            highlights_json = json.load(f)

        for category in highlights_json.keys():
            # Send category as a separate message
            category_message = f"**{category}**"
            send_message(channel_id, category_message, headers, posturl)

            for article_block in highlights_json[category]["article_blocks"]:
                for article in article_block["articles"]:
                    # Send each article as a separate message
                    websitename = article["link"].split("/")[2].replace("www.", "")
                    article_message = f"* [{websitename} | {article['title']}]({article['link']})"
                    send_message(channel_id, article_message, headers, posturl)

        
        # Upload the video
        data = {'channel_id': channel_id}
        headers = {'Authorization': f'Bearer {bot_token}'}
        files = {'files': open(video_message_file_path, 'rb')}
        
        response = requests.post(uploadurl, headers=headers, data=data, files=files)
        if response.status_code != 201:
            raise Exception(f"Failed to upload video: {response.content}")
        
        video_file_id = response.json()["file_infos"][0]['id']

        # Then, we create a post with the uploaded files
        headers = {
            'Authorization': f'Bearer {bot_token}',
            'Content-Type': 'application/json'
            }

        video_summary_message = "Here is your daily news summary:"
        send_message(channel_id, video_summary_message, headers, posturl, [video_file_id])

        # remove folder with the news and the video
        # os.system(f"rm -rf {folder_path}")

        return True


    except Exception:
        process_error(f"While sending video summary to chat", traceback=traceback.format_exc())


if __name__ == "__main__":
    send_video_summary_to_chat()