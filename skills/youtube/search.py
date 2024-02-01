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

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from skills.youtube.get_video_details import get_video_details
from typing import Literal
from datetime import datetime, timedelta
from skills.all_skills import *


@skill_function(
    skill=YouTube(),
    function_name="Search videos",
    function_icon="search"
)
def search_youtube(
        query: str, 
        max_results: int = 20, 
        order: Literal["date", "rating", "relevance", "title", "videoCount", "viewCount"] = "viewCount",
        type: str = "video",
        region: str = "US",  # default to United States
        include_more_details: bool = True,
        max_age_days: int = 365
        ) -> list:
    try:
        add_to_log(module_name="YouTubeAPI", color="blue", state="start")
        add_to_log("Searching YouTube ...")
        secrets = load_secrets()
        
        youtube = build('youtube', 'v3', developerKey=secrets["YOUTUBE_API_KEY"])
        
        # Calculate the publishedAfter parameter if max_age_days is set
        published_after = None
        if max_age_days is not None:
            published_after = (datetime.now() - timedelta(days=max_age_days)).isoformat("T") + "Z"
        
        search_response = youtube.search().list(
            q=query,
            part='id,snippet',
            maxResults=max_results,
            order=order,
            type=type,
            regionCode=region,
            publishedAfter=published_after
        ).execute()
        
        videos = []
        
        for search_result in search_response.get('items', []):
            video_info = {
                "title": search_result['snippet']['title'],
                "url": f"https://www.youtube.com/watch?v={search_result['id']['videoId']}",
                "description": search_result['snippet']['description'],
                "thumbnail": search_result['snippet']['thumbnails']['high']['url'],
                "publishedAt": search_result['snippet']['publishedAt'],
                "channel": {
                    "title": search_result['snippet']['channelTitle'],
                    "url": f"https://www.youtube.com/channel/{search_result['snippet']['channelId']}"
                }
            }
            # if include_more_details is True, get more details about the video
            if include_more_details:
                extended_video_details = get_video_details(video_info["url"])
                video_info["description"] = extended_video_details["description"]
                video_info["duration_h_m_s"] = extended_video_details["duration_h_m_s"]
                video_info["statistics"] = extended_video_details["statistics"]
            
            videos.append(video_info)
        
        add_to_log(f"Found {len(videos)} videos", state="success")
        return videos
    
    except HttpError as e:
        process_error(f"An HTTP error {e.resp.status} occurred:\n{e.content}", traceback=traceback.format_exc())
        return None
    except Exception as e:
        process_error(f"Failed to search YouTube: {str(e)}", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import subprocess
    import json

    videos = search_youtube(query="Apple Vision Pro")
    
    # save to a json file and open it in code
    json_filename = f"{main_directory}/temp_data/youtube_search_results/youtube_search_results.json"
    # make the directory if it doesn't exist
    os.makedirs(os.path.dirname(json_filename), exist_ok=True)

    with open(json_filename, "w") as f:
        json.dump(videos, f, indent=4)
    
    subprocess.run(["code", json_filename])