from PIL import Image
from io import BytesIO
from typing import Literal, Optional

def resize_image_processing(
    image_data: bytes,
    target_resolution_width: Optional[int] = None,
    target_resolution_height: Optional[int] = None,
    max_length: Optional[int] = None,
    method: Literal["scale", "crop"] = "scale",
    use_ai_upscaling_if_needed: bool = True,
    output_format: Optional[str] = None,
    output_square: bool = False
) -> bytes:
    """
    Resize an image to the target resolution
    """

    # Load the image
    image = Image.open(BytesIO(image_data))

    # Calculate the target resolution
    if max_length is not None:
        aspect_ratio = image.width / image.height
        if output_square:
            if aspect_ratio > 1:
                target_resolution_height = max_length
                target_resolution_width = int(max_length * aspect_ratio)
            else:
                target_resolution_width = max_length
                target_resolution_height = int(max_length / aspect_ratio)
        else:
            if aspect_ratio > 1:
                target_resolution_width = max_length
                target_resolution_height = int(max_length / aspect_ratio)
            else:
                target_resolution_height = max_length
                target_resolution_width = int(max_length * aspect_ratio)
    elif target_resolution_width is not None and target_resolution_height is None:
        aspect_ratio = image.width / image.height
        target_resolution_height = int(target_resolution_width / aspect_ratio)
    elif target_resolution_height is not None and target_resolution_width is None:
        aspect_ratio = image.width / image.height
        target_resolution_width = int(target_resolution_height * aspect_ratio)
    elif target_resolution_width is None and target_resolution_height is None:
        target_resolution_width, target_resolution_height = image.size

    # Determine the resize method
    resize_method = Image.BICUBIC if method == "scale" else Image.NEAREST

    # Resize the image if method is "scale"
    if method == "scale":
        image = image.resize((target_resolution_width, target_resolution_height), resize_method)

    # If method is "crop", crop the image to the specified resolution from the center
    if method == "crop":
        left = (image.width - target_resolution_width) / 2
        top = (image.height - target_resolution_height) / 2
        right = (image.width + target_resolution_width) / 2
        bottom = (image.height + target_resolution_height) / 2
        image = image.crop((left, top, right, bottom))

    # If output_square is requested, crop the image to a square from the center
    if output_square:
        min_dimension = min(image.width, image.height)
        left = (image.width - min_dimension) / 2
        top = (image.height - min_dimension) / 2
        right = (image.width + min_dimension) / 2
        bottom = (image.height + min_dimension) / 2
        image = image.crop((left, top, right, bottom))

    # Convert the image back to bytes
    byte_arr = BytesIO()
    image.save(byte_arr, format=output_format or image.format or 'JPEG')
    return byte_arr.getvalue()