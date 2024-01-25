from googleapiclient.discovery import build

import sys
import os
import re
from datetime import timedelta


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
OpenMates_directory = re.sub('OpenMates.*', 'OpenMates', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = f"{OpenMates_directory}/secrets/youtube_api_credentials.json"

def convert_duration(duration):
    duration_regex = re.compile('PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
    hours, minutes, seconds = duration_regex.match(duration).groups()
    hours = int(hours) if hours else 0
    minutes = int(minutes) if minutes else 0
    seconds = int(seconds) if seconds else 0
    td = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return str(td)


def get_video_details(url:str) -> dict:
    secrets = load_secrets()

    # Extract video id from url
    video_id = url.split('=')[1]

    # Create a YouTube service object
    youtube = build('youtube', 'v3', developerKey=secrets["youtube_api_key"])

    # Get the video details
    request = youtube.videos().list(
        part="snippet,contentDetails",
        id=video_id
    )
    response = request.execute()

    # Extract details from the response
    details = response['items'][0]
    title = details['snippet']['title']
    channel = details['snippet']['channelTitle']
    description = details['snippet']['description']
    duration = convert_duration(details['contentDetails']['duration'])

    return {
        "url": url,
        "title": title,
        "channel": channel,
        "description": description,
        "duration_h_m_s": duration,
    }

if __name__ == "__main__":
    url = "https://www.youtube.com/watch?v=O6d1RKYapFI"
    api_key = ""
    video_details = get_video_details(url)
    print(video_details)