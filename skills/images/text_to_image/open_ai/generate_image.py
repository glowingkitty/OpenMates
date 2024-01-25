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

from skills.images.text_to_image.open_ai.get_costs_image_generation import get_costs_image_generation
from skills.images.text_to_image.open_ai.post_to_api_usage_image_generation import post_to_api_usage_image_generation

from PIL import Image, PngImagePlugin
from io import BytesIO
from openai import OpenAI, RateLimitError, APITimeoutError, InternalServerError
import time
import requests
import uuid
from typing import Literal

# follow instructions https://platform.openai.com/docs/api-reference/images/create


def generate_image(
        prompt: str,
        image_shape: Literal['square', 'horizontal', 'vertical'] = 'square',
        quality: Literal['standard','hd'] = 'standard',
        model: str = 'dall-e-3',
        save_image: bool = False) -> dict:
    
    try:
        add_to_log(state="start", module_name="Images | Text to image | OpenAI", color="yellow")
        add_to_log("Prepare to generate image...")
        
        secrets = load_secrets()
        config = load_config()
        
        image_shapes = {
            'square': '1024x1024',
            'horizontal': '1792x1024',
            'vertical': '1024x1792'
        }

        if image_shape not in image_shapes:
            raise ValueError(f"Invalid image_shape ({image_shape}). Please use one of the following: {image_shapes.keys()}")
        
        size = image_shapes[image_shape]

        client = OpenAI(api_key=secrets["OPENAI_API_KEY"])

        # Get the predicted costs of the image generation
        costs = get_costs_image_generation(image_shape=image_shape, quality=quality, model_name=model)
        if not costs:
            add_to_log("Failed to get the costs for the image generation.", state="error")
            return None
        
        # Warn about the costs in log
        add_to_log(f"You are about to spend {round(costs['total_costs'], 4)} {costs['currency']} for generating the image.")

        if config["environment"] == "development":
            add_to_log("Press CTRL+C to cancel or wait 5 seconds to auto continue ...")
            time.sleep(5)

        image_info = {}
        max_retries = 5
        retries = 0

        while retries < max_retries:
            try:
                add_to_log(f"Generating a {image_shape} image for the prompt: '{prompt}' ...")
                response = client.images.generate(
                    model=model,
                    prompt=prompt,
                    size=size,
                    quality=quality,
                    n=1,
                )

                for image_data in response.data:
                    if save_image:
                        if not os.path.exists(f"{main_directory}/temp_data/images"):
                            os.makedirs(f"{main_directory}/temp_data/images")
                            
                        image_url = image_data.url
                        image_response = requests.get(image_url)
                        if image_response.status_code == 200:
                            unique_filename = f'image_{uuid.uuid4()}.png'  # Generate unique filename
                            image = Image.open(BytesIO(image_response.content))

                            # Add EXIF comment
                            meta = PngImagePlugin.PngInfo()
                            meta.add_text("Description", f"Original Prompt: {prompt}, Revised Prompt: {image_data.revised_prompt}")
                            image.save(f"{main_directory}/temp_data/images/{unique_filename}", "PNG", pnginfo=meta)
                    
                    image_info = {
                        "image_url": image_data.url,
                        "prompt": prompt,
                        "revised_prompt": image_data.revised_prompt
                    }

                # post to API usage
                post_to_api_usage_image_generation(image_shape=image_shape, quality=quality, model=model)

                add_to_log(f"Successfully generated a {quality} {image_shape} image for the prompt: '{prompt}'.", state="success")
                add_to_log(f"Your image is available here: {image_info['image_url']}", state="success")

                return image_info
            

            except KeyboardInterrupt:
                shutdown()

            except RateLimitError as e:
                if retries == max_retries:
                    raise RateLimitError(f"An error occurred: {e}")
                
                add_to_log("OpenAI API rate limit reached. Waiting 60 seconds...") 
                time.sleep(60)
                retries += 1
                continue

            except APITimeoutError as e:
                if retries == max_retries:
                    raise APITimeoutError(f"An error occurred: {e}")
                
                add_to_log("OpenAI API timeout. Waiting 60 seconds...") 
                time.sleep(60)
                retries += 1
                continue

            except InternalServerError as e:
                if retries == max_retries:
                    raise InternalServerError(f"An error occurred: {e}")
                
                add_to_log("OpenAI API internal server error. Waiting 60 seconds...") 
                time.sleep(60)
                retries += 1
                continue

            except Exception:
                process_error("Failed to generate an image", traceback=traceback.format_exc())

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to generate image", traceback=traceback.format_exc())
        return None


if __name__ == "__main__":
    prompt = "A portrait photo of a journalist. Super detailed, high resolution."
    save_image = True

    generate_image(prompt=prompt, save_image=save_image)