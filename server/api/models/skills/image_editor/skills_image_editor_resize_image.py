
################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


# POST /{team_slug}/skills/image_editor/resize (resize an image)

image_editor_resize_output_example = {
    "image/jpeg": "data:image/jpeg;base64..."
}