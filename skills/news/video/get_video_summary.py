import traceback
import sys
import os
import re
import datetime
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips
import json
import shutil

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from skills.speech.open_ai.text_to_speech import text_to_speech
from skills.news.video.get_news_video_outline import get_news_video_outline
from skills.cloud_storage.dropbox.upload_file import upload_file
from skills.design.create_website_preview_image import create_website_preview_image


def get_video_summary(
        use_existing_file_if_exists: bool = False,
        upload: bool = True,
        delete_temp_files: bool = True) -> str:
    try:
        add_to_log(state="start", module_name="News Update", color="cyan")

        current_date = datetime.datetime.now().strftime("%Y_%m_%d")
        news_folder_path = os.path.join(main_directory, "Bot", "temp_data", "news", current_date)
        background_music_folder_path = os.path.join(main_directory, "Bot", "apps", "video", "background_music")
        default_images_folder_path = os.path.join(main_directory, "Bot", "apps", "news", "video")
        video_filename = os.path.join(news_folder_path, f"news_video_{current_date}.mp4")

        add_to_log(f"Start getting video summary of news highlights for {current_date} ...")

        # check if the file already exists, if so, return it
        if use_existing_file_if_exists and os.path.exists(video_filename):
            add_to_log(f"\U00002714 Using existing file: news_video_{current_date}.mp4")
            return video_filename

        # else, create a new video
        os.makedirs(news_folder_path, exist_ok=True)

        add_to_log(f"Loading video script for the news update for {current_date} ...")
        video_script = get_news_video_outline(use_existing_file_if_exists=use_existing_file_if_exists)
        if not video_script:
            return None

        # TODO load dropbox links from existing file if it exists
        dropbox_links = {"links": []}
        clips = []
        total_duration = 0
        last_image_path = None

        for clip_info in video_script["clips"]:
            audio_duration = 0
            
            if "speech" in clip_info:
                # TODO check if audio file already exists, if so, use it
                speech_file_path = text_to_speech(input_text=clip_info["speech"])
                speech_audio = AudioFileClip(speech_file_path)
                audio_duration = speech_audio.duration
                total_duration += audio_duration

            if "background_image" in clip_info:
                background_image_path = os.path.join(default_images_folder_path, clip_info["background_image"])
                last_image_path = background_image_path

            if "link" in clip_info:
                # TODO load existing image if it exists (from dropbox_links or else local and add to dropbox)
                background_image_path = create_website_preview_image(clip_info["link"])
                last_image_path = background_image_path
                
                dropbox_url = upload_file(
                    filepath=background_image_path,
                    target_path=f"/api_uploads/OpenMates/news/{current_date}/article_images/",
                    share_file=True
                    )
                dropbox_links["links"].append(dropbox_url)

            if last_image_path:
                img_clip = ImageClip(background_image_path).set_duration(audio_duration)
                img_clip.set_audio(speech_audio)
                clips.append(img_clip)

        with open(os.path.join(news_folder_path, "dropbox_links.json"), "w") as f:
            json.dump(dropbox_links, f, indent=4)

        # Load the background audio
        background_audio = AudioFileClip(os.path.join(background_music_folder_path, video_script["background_music"]["file"]))
        
        # Check if the background audio should play for the full duration of the video
        if video_script["background_music"]["duration"] == "full":
            # Initialize a list to hold the audio clips
            audio_clips = [background_audio]
            current_duration = background_audio.duration

            # Loop until the total duration is reached
            while current_duration < total_duration:
                remaining_duration = total_duration - current_duration
                next_clip = background_audio.subclip(0, min(remaining_duration, background_audio.duration))
                audio_clips.append(next_clip)
                current_duration += next_clip.duration

            # Concatenate the clips to match the total duration as closely as possible
            background_audio = concatenate_audioclips(audio_clips)
            background_audio = background_audio.volumex(0.3)

        final_clip = concatenate_videoclips(clips)
        final_clip = final_clip.set_audio(background_audio)

        # TODO fix that background audio is overwriting the audio of the existing clips

        final_clip.write_videofile(video_filename, fps=24, audio_codec="aac")

        if upload:
            dropbox_link = upload_file(
                filepath=video_filename,
                target_path=f"/api_uploads/OpenMates/news/{current_date}/videos/",
                share_file=True
                )
            # delete the news folder and all it's files
            if delete_temp_files and os.path.isdir(news_folder_path):
                shutil.rmtree(news_folder_path)

            return dropbox_link
        
        return video_filename

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed getting video summary of news highlights.", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    video_file_path = get_video_summary(
        use_existing_file_if_exists=True,
        delete_temp_files=False)
    print(video_file_path)