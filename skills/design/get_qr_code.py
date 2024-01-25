import qrcode
from qrcode.image.svg import SvgPathImage
import os
import re
import sys
import traceback
from slugify import slugify

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error
from skills.tinyurl.get_short_url import get_short_url


def get_qr_code(
        url: str,
        shorten_url: bool = True,
        fill_color: str = "#A0A0A0", # grey color for the QR code.
        url_shortener: str = "tinyurl",
        return_svg_content: bool = False,
        filepath: str = None) -> str:
    try:
        # get slugified filename
        filename = slugify(url)
        if not filepath:
            folderpath = f'{main_directory}temp_data/qr'
            filepath = f'{folderpath}/{filename}.svg'
        else:
            folderpath = os.path.dirname(filepath)

        # if the url is not shortened, shorten it
        if url_shortener not in url and shorten_url:
            url = get_short_url(url=url)

        # Create a QR code instance
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,)

        # Add data to the QR code
        qr.add_data(url)
        qr.make(fit=True)

        # Create an SVG image with the specified hex colors
        img = qr.make_image(image_factory=SvgPathImage)

        # Save the SVG image to a file
        # make sure the directory exists, create it if it doesn't, in one command
        os.makedirs(folderpath, exist_ok=True)
        with open(filepath, "wb") as f:
            img.save(f)

        with open(filepath, 'r') as file:
            svg_content = file.read()

        # Replace the fill color
        svg_content = svg_content.replace('fill="#000000"', f'fill="{fill_color}"')

        with open(filepath, 'w') as file:
            file.write(svg_content)

        if return_svg_content:
            # delete the local file
            os.remove(filepath)
            return svg_content
        
        else:
            return filepath

    except Exception:
        process_error("Failed creating a QR code.", traceback=traceback.format_exc())


if __name__ == "__main__":
    file_path = get_qr_code(url="https://www.theverge.com/23951210/energy-secretary-jennifer-granholm-interview-sustainability")
    print(file_path)