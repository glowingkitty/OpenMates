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

from typing import Literal


def get_costs_image_generation(
        image_shape: Literal['square', 'horizontal', 'vertical'] = 'square',
        quality: Literal['standard','hd'] = 'standard',
        model_name: str = "dall-e-3",
        currency: str = "USD") -> dict:
    try:
        add_to_log(state="start", module_name="Images | Text to image | OpenAI", color="yellow")
        # if the image_shape is not valid, return None
        if image_shape not in ["square", "horizontal", "vertical"]:
            raise ValueError(f"The image_shape {image_shape} is not valid. Please use one of the following: square, horizontal, vertical")
        if quality not in ["standard", "hd"]:
            raise ValueError(f"The quality {quality} is not valid. Please use one of the following: standard, hd")

        add_to_log(f"Calculating the costs for a {quality} {image_shape} image using the {model_name} model...")
        prices_per_image = {
            "square": {"standard": 0.04, "hd": 0.08},
            "horizontal": {"standard": 0.08, "hd": 0.12},
            "vertical": {"standard": 0.08, "hd": 0.12}
        }

        # calculate the costs
        total_costs = prices_per_image[image_shape][quality]

        add_to_log(state="success", message=f"Successfully calculated the costs for a {quality} {image_shape} image using the {model_name} model:")
        add_to_log(state="success", message=total_costs)

        return {
            "total_costs": total_costs,
            "currency": currency
            }
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed getting the cost for a {image_shape} image using the {model_name} model", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    # test the function with the arguments from the command line
    image_shape = sys.argv[1]

    get_costs_image_generation(
        image_shape=image_shape
    )