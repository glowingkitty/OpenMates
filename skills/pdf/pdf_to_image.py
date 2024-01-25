################

# Default Imports

################
import sys
import os
import re
from pdf2image import convert_from_path

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.vision.open_ai.prepare_image import prepare_image


def pdf_to_image(filepath: str, prepare_for_vision_model: bool = True) -> list:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log("Converting PDF to images ...")

        # Ensure the PDF file exists
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"PDF file not found: {filepath}")

        # Replace spaces in the filename with underscores
        original_filename = os.path.basename(filepath)
        filename = os.path.basename(filepath).replace(".pdf", "").replace(" ", "_").replace("-", "_")
        new_filepath = os.path.join(os.path.dirname(filepath), f"{filename}.pdf")
        os.rename(filepath, new_filepath)
        filepath = new_filepath

        # Create a temporary directory to store images
        temp_dir = f"{main_directory}temp_data/pdf_to_image/{filename}"
        os.makedirs(temp_dir, exist_ok=True)
        images = convert_from_path(filepath, output_folder=temp_dir)
        image_paths = []

        # Save images to temporary directory and collect file paths
        for i, image in enumerate(images):
            image_path = os.path.join(temp_dir, f"page_{i+1}.png")
            image.save(image_path, 'PNG')
            image_paths.append(image_path)

            # Scale down images for vision model
            if prepare_for_vision_model:
                prepare_image(input_file_path=image_path, save_file=True, output_file_path=image_path)

        # remove all temp .ppm files in the temp directory
        for file in os.listdir(temp_dir):
            if file.endswith(".ppm"):
                os.remove(os.path.join(temp_dir, file))

        # rename back to original filename
        os.rename(filepath, os.path.join(os.path.dirname(filepath), original_filename))

        add_to_log(f"Successfully converted PDF to images", state="success")
        return image_paths

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to convert PDF to images.", traceback=traceback.format_exc())
        return []

if __name__ == "__main__":
    # process pdf files in the folder of the script
    pdf_files = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for file in os.listdir(script_dir):
        if file.endswith(".pdf"):
            pdf_files.append(os.path.join(script_dir, file))  # include the full path
    for pdf_file in pdf_files:
        image_paths = pdf_to_image(pdf_file)

        # for each image bath, move file to current folder and rename it to filename + page number
        for i, image_path in enumerate(image_paths):
            filename = os.path.basename(pdf_file).replace(".pdf", "")
            new_image_path = f"{script_dir}/{filename}_page_{i+1}.png"
            os.rename(image_path, new_image_path)