import traceback
import requests
from PIL import Image, ImageOps, ImageFilter
import io
import base64
import sys
import os
import re
import time


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *


def prepare_image(
        image_bytes: bytes = None, 
        input_file_path: str = None, 
        save_file: bool = False, 
        output_file_path: str = 'output.jpg',
        jpeg_quality: int = 100  # Add a parameter for JPEG quality
    ) -> bytes:
    try:
        add_to_log(module_name="Vision | OpenAI", state="start", color="yellow")
        add_to_log("Preparing the image for the vision model ...")

        config = load_config()

        image = None

        # Check if input_file_path is a URL and download the image
        if input_file_path and (input_file_path.startswith('http://') or input_file_path.startswith('https://')):
            max_attempts = 3
            attempt = 0
            headers = {'User-Agent': config["user_agent"]["official"]}
            while attempt < max_attempts:
                try:
                    response = requests.get(input_file_path,headers=headers)
                    response.raise_for_status()  # Will raise an HTTPError if the HTTP request returned an unsuccessful status code
                    image_bytes = response.content
                    break  # If the request is successful, break out of the loop
                except requests.exceptions.HTTPError as e:
                    print(f"Attempt {attempt + 1} failed: {e}")
                    attempt += 1
                    if attempt < max_attempts:
                        time.sleep(3)
                    else:
                        raise ValueError("Failed to download image after maximum retry attempts")
            image = Image.open(io.BytesIO(image_bytes))
        elif input_file_path:
            # Load image from file
            image = Image.open(input_file_path)
            # Convert PNG to RGB if necessary
            if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                image = image.convert('RGB')
        elif image_bytes:
            # Load image from bytes
            image = Image.open(io.BytesIO(image_bytes))
            # Convert PNG to RGB if necessary
            if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                image = image.convert('RGB')
        else:
            raise ValueError("No valid input provided for image processing")

        image = ImageOps.exif_transpose(image)

        # Get the dimensions
        width, height = image.size

        # Determine the target size in one step
        target_width, target_height = width, height
        if max(width, height) > 2048:
            if width > height:
                target_width = 2048
                target_height = int((height * 2048) / width)
            else:
                target_height = 2048
                target_width = int((width * 2048) / height)
        if min(target_width, target_height) > 768:
            if target_width < target_height:
                target_width = 768
                target_height = int((height * 768) / width)
            else:
                target_height = 768
                target_width = int((width * 768) / height)

        # Resize the image in one step
        image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)

        # Optional: Apply a sharpening filter
        image = image.filter(ImageFilter.SHARPEN)

        # Convert PIL Image back to bytes
        byte_arr = io.BytesIO()
        image.save(byte_arr, format='JPEG', quality=jpeg_quality, progressive=True)
        encoded_image = base64.b64encode(byte_arr.getvalue()).decode('utf-8')

        # Save the file if save_file is True
        if save_file:
            image.save(output_file_path, 'JPEG', quality=jpeg_quality, progressive=True)

        add_to_log("Successfully prepared the image for the vision model", state="success")
        return encoded_image
    
    except Exception:
        process_error("Failed to prepare the image for the vision model", traceback=traceback.format_exc())