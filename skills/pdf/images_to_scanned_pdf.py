################

# Default Imports

################
import sys
import os
import re
from PIL import ImageOps, Image, ImageEnhance
import pytesseract
import fitz  # PyMuPDF
import img2pdf
import tempfile

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

def images_to_scanned_pdf(filepaths: list, delete_originals: bool = True) -> str:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log("Processing images and converting to a scanned PDF ...")

        # check if the filepaths are images and exist
        for filepath in filepaths:
            if not os.path.isfile(filepath):
                add_to_log(f"File not found: {filepath}", state="error")
                return None
            if not filepath.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):
                add_to_log(f"File is not an image: {filepath}", state="error")
                return None

        # Create a PDF document
        pdf_doc = fitz.open()

        for image_path in filepaths:
            # Open the image
            image = Image.open(image_path)
            # Correct the orientation based on EXIF data
            image = ImageOps.exif_transpose(image)
            # Crop, enhance, and convert to black and white
            image = image.crop(image.getbbox())
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.5)  # Reduce the contrast enhancement factor
            image = image.convert('L')  # Convert to grayscale instead of black and white

            # OCR
            text = pytesseract.image_to_string(image, lang='eng+deu')

            # Save the processed image to a temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            image.save(temp_file, 'PNG')
            temp_file.close()

            # Convert image to PDF
            with open(temp_file.name, 'rb') as f:
                pdf_bytes = img2pdf.convert(f.read())
            img_pdf = fitz.open("pdf", pdf_bytes)
            page = img_pdf[0]
            # Add text as overlay (hidden text for searchability)
            page.insert_text((0, 0), text, fontsize=1, render_mode=0)

            # Append to the document
            pdf_doc.insert_pdf(img_pdf)

            # Delete the temporary file
            os.remove(temp_file.name)

            # Optionally delete the original image
            if delete_originals:
                os.remove(image_path)

        # Create a filename based on the names of the images
        image_names = [os.path.splitext(os.path.basename(filepath))[0] for filepath in filepaths]
        filename = '_'.join(image_names) + '_processed.pdf'

        # Save the PDF document
        output_directory = os.path.dirname(filepaths[0])
        output_path = os.path.join(output_directory, filename)
        pdf_doc.save(output_path)
        pdf_doc.close()

        add_to_log(f"Successfully created the scanned PDF: {output_path}", state="success")
        return output_path

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to convert images to scanned PDF", traceback=traceback.format_exc())
        return None


if __name__ == "__main__":
    # Example usage:
    # Replace 'image_file_paths' with the actual paths to your image files
    image_file_paths = ['IMG_9968.jpeg', 'IMG_9969.jpeg']

    current_folder_path = os.path.dirname(os.path.abspath(__file__))
    image_file_paths = [os.path.join(current_folder_path, path) for path in image_file_paths]
    result_pdf = images_to_scanned_pdf(filepaths=image_file_paths, delete_originals=False)
    print(f"Scanned PDF created at: {result_pdf}")