################

# Default Imports

################
import sys
import os
import re
import traceback
import json
import datetime
import moviepy.editor as mp
import numpy as np
from PIL import Image
from pymp4.parser import Box


# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.video.get_video_rotation import get_set_rotation
from skills.hearing.open_ai.transcript import transcript



def rotate_image(image, rotation):
    image_pil = Image.fromarray(image)
    if rotation == 90:
        image_pil = image_pil.rotate(270, expand=True)
    elif rotation == 180:
        image_pil = image_pil.rotate(180, expand=True)
    elif rotation == 270:
        image_pil = image_pil.rotate(90, expand=True)
    
    # Resize the image to its original dimensions after rotation
    image_pil = image_pil.resize((image.shape[1], image.shape[0]))

    # Rotate the image back to its original orientation
    if rotation == 90:
        image_pil = image_pil.rotate(90, expand=True)
    elif rotation == 180:
        image_pil = image_pil.rotate(180, expand=True)
    elif rotation == 270:
        image_pil = image_pil.rotate(270, expand=True)
    
    return np.array(image_pil)


def video_to_images_and_text(filepath: str = None) -> dict:
    try:
        add_to_log(module_name="Video to Images + Text", color="yellow", state="start")
        add_to_log("Processing the video ...")

        # make sure the file exists
        if filepath and not os.path.exists(filepath):
            add_to_log(f"The file does not exist: '{filepath}'", state="error")
            return None
        
        # Open the video file and get the rotation metadata
        rotation = get_set_rotation(filepath)

        # Ensure the temp_data directory exists
        filename_without_extension = os.path.splitext(os.path.basename(filepath))[0]
        output_folder = f'{main_directory}temp_data/video_to_images_and_text/{filename_without_extension}'
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        # Load the video and get its duration
        video = mp.VideoFileClip(filepath)
        duration = video.duration

        # Determine the interval for screenshots
        # interval = 0.5 if duration < 15 else 1
        interval = 1

        # Initialize the output dictionary
        output_dict = {"clips": []}

        # Process the video in 5-second clips
        for start_time in range(0, int(duration), 5):
            end_time = min(start_time + 5, duration)
            clip = video.subclip(start_time, end_time)
                
            clip_audio_filepath = os.path.join(output_folder, f"{start_time}_audio.wav")
            clip.audio.write_audiofile(clip_audio_filepath)

            # Extract transcript
            clip_transcript = transcript(clip_audio_filepath)

            # Delete the audio file
            os.remove(clip_audio_filepath)

            # Take screenshots
            screenshots = []
            current_time = start_time
            while current_time < end_time:
                screenshot_filename = f"{datetime.timedelta(seconds=int(current_time)).__str__().replace(':', '_')}_{int((current_time - int(current_time)) * 1000)}.jpg"
                screenshot_filepath = os.path.join(output_folder, screenshot_filename)
                image = clip.get_frame(current_time - start_time)
                rotated_image = rotate_image(image, rotation)
                image_pil = Image.fromarray(rotated_image)
                image_pil.save(screenshot_filepath)
                screenshots.append(screenshot_filepath)
                current_time += interval

            # Add clip information to the output dictionary
            output_dict["clips"].append({
                "time": f"{datetime.timedelta(seconds=start_time)} - {datetime.timedelta(seconds=end_time)}",
                "transcript": clip_transcript,
                "screenshots": screenshots
            })

        # save the output dictionary to a json file
        output_filepath = os.path.join(output_folder, "output.json")
        with open(output_filepath, "w") as f:
            json.dump(output_dict, f, indent=4)
        
        add_to_log("Successfully processed the video", state="success", module_name="Video to Images + Text")
        return output_dict

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to process the video", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    file = "testvideo.MOV"
    # assume the file is in the same directory as this script
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file)
    video_to_images_and_text(filepath=path)