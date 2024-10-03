from PIL import Image
from io import BytesIO
from typing import Literal, Optional

from server.api.models.apps.photos.skills_photos_resize_image import ImageEditorResizeImageInput
from fastapi.responses import StreamingResponse


def resize_image(
    image_data: bytes,
    target_resolution_width: Optional[int] = None,
    target_resolution_height: Optional[int] = None,
    max_length: Optional[int] = None,
    method: Literal["scale", "crop"] = "scale",
    use_ai_upscaling_if_needed: bool = True,
    output_square: bool = False
) -> StreamingResponse:
    """
    Resize an image to the target resolution
    """

    input_data = ImageEditorResizeImageInput(
        image_data=image_data,
        target_resolution_width=target_resolution_width,
        target_resolution_height=target_resolution_height,
        max_length=max_length,
        method=method,
        use_ai_upscaling_if_needed=use_ai_upscaling_if_needed,
        output_square=output_square
    )

    # Load the image
    image = Image.open(BytesIO(input_data.image_data))

    # Calculate the target resolution
    if input_data.max_length is not None:
        aspect_ratio = image.width / image.height
        if input_data.output_square:
            if aspect_ratio > 1:
                input_data.target_resolution_height = input_data.max_length
                input_data.target_resolution_width = int(input_data.max_length * aspect_ratio)
            else:
                input_data.target_resolution_width = input_data.max_length
                input_data.target_resolution_height = int(input_data.max_length / aspect_ratio)
        else:
            if aspect_ratio > 1:
                input_data.target_resolution_width = input_data.max_length
                input_data.target_resolution_height = int(input_data.max_length / aspect_ratio)
            else:
                input_data.target_resolution_height = input_data.max_length
                input_data.target_resolution_width = int(input_data.max_length * aspect_ratio)
    elif input_data.target_resolution_width is not None and input_data.target_resolution_height is None:
        aspect_ratio = image.width / image.height
        input_data.target_resolution_height = int(input_data.target_resolution_width / aspect_ratio)
    elif input_data.target_resolution_height is not None and input_data.target_resolution_width is None:
        aspect_ratio = image.width / image.height
        input_data.target_resolution_width = int(input_data.target_resolution_height * aspect_ratio)
    elif input_data.target_resolution_width is None and input_data.target_resolution_height is None:
        input_data.target_resolution_width, input_data.target_resolution_height = image.size

    # Determine the resize method
    resize_method = Image.BICUBIC if input_data.method == "scale" else Image.NEAREST

    # Resize the image if method is "scale"
    if input_data.method == "scale":
        image = image.resize((input_data.target_resolution_width, input_data.target_resolution_height), resize_method)

    # If method is "crop", crop the image to the specified resolution from the center
    if input_data.method == "crop":
        left = (image.width - input_data.target_resolution_width) / 2
        top = (image.height - input_data.target_resolution_height) / 2
        right = (image.width + input_data.target_resolution_width) / 2
        bottom = (image.height + input_data.target_resolution_height) / 2
        image = image.crop((left, top, right, bottom))

    # If output_square is requested, crop the image to a square from the center
    if input_data.output_square:
        min_dimension = min(image.width, image.height)
        left = (image.width - min_dimension) / 2
        top = (image.height - min_dimension) / 2
        right = (image.width + min_dimension) / 2
        bottom = (image.height + min_dimension) / 2
        image = image.crop((left, top, right, bottom))

    # Convert the image back to bytes
    byte_arr = BytesIO()
    image.save(byte_arr, format='JPEG')

    return StreamingResponse(BytesIO(byte_arr.getvalue()), media_type="image/jpeg")