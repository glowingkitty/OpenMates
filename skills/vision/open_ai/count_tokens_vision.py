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


def count_tokens_vision(width_px: int, height_px: int, detail: str = 'high') -> float:
    try:
        add_to_log(module_name="Vision | OpenAI", state="start", color="yellow")
        add_to_log("Calculating the token cost for vision ...")

        if detail == 'low':
            token_cost = 85  # Fixed cost for low detail images
            add_to_log(f"Successfully calculated the token cost: {token_cost} (fixed for low detail)", state="success")
            return token_cost

        # Scale down the image to fit within a 2048 x 2048 square if necessary
        max_dimension = max(width_px, height_px)
        if max_dimension > 2048:
            scale_factor = 2048 / max_dimension
            width_px = int(width_px * scale_factor)
            height_px = int(height_px * scale_factor)

        # Scale the image such that the shortest side is 768px long
        min_dimension = min(width_px, height_px)
        scale_factor = 768 / min_dimension
        width_px = int(width_px * scale_factor)
        height_px = int(height_px * scale_factor)

        # Calculate the number of 512px squares needed
        num_tiles_width = -(-width_px // 512)  # Ceiling division
        num_tiles_height = -(-height_px // 512)  # Ceiling division
        num_tiles = num_tiles_width * num_tiles_height

        print(num_tiles)

        # Calculate the final token cost
        token_cost = 170 * num_tiles + 85

        add_to_log(f"Successfully calculated the token cost: {token_cost}", state="success")

        return token_cost

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to calculate the token cost", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    # video_length_seconds = (25)
    # analyze_frame_rate = 1 # 1 frame per second
    # total_frames = video_length_seconds * analyze_frame_rate
    # TODO this calculation is not correct it seems, need to fix the code
    width_px = 900
    height_px = 506
    detail = 'high'
    total_frames = 15
    costs_per_frame = count_tokens_vision(width_px=width_px, height_px=height_px, detail=detail)
    total_costs = costs_per_frame * total_frames
    print(f"Total tokens: {total_costs}")