# backend/scripts/verify_c2pa.py
import sys
import os
import io
import json
import logging

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add the project root to sys.path
sys.path.append(os.getcwd())

from backend.core.api.app.utils.image_processing import process_image_for_storage, HAS_C2PA
from PIL import Image

def verify():
    print(f"Checking C2PA availability: {HAS_C2PA}")
    if not HAS_C2PA:
        print("ERROR: c2pa-python is not installed. Please rebuild the api container.")
        return

    # Create a dummy image
    img = Image.new('RGB', (200, 200), color = (73, 109, 137))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    image_bytes = img_byte_arr.getvalue()

    metadata = {
        "prompt": "A beautiful sunset over the mountains",
        "model": "Flux.1 Pro",
        "software": "OpenMates AI",
        "generated_at": "2026-01-20T12:00:00Z"
    }

    print("Processing image with C2PA metadata...")
    results = process_image_for_storage(image_bytes, metadata=metadata)

    for key, data in results.items():
        size = len(data)
        has_jumb = b'jumb' in data.lower()
        print(f"Format: {key:12} | Size: {size:7} bytes | C2PA JUMBF: {'YES' if has_jumb else 'NO'}")

    if any(b'jumb' in data.lower() for data in results.values()):
        print("\nSUCCESS: C2PA manifests were successfully injected into the images.")
        print("Note: These are signed with a self-signed certificate and may show as 'unverified' in some viewers, but the technical structure is present.")
    else:
        print("\nFAILURE: No C2PA manifests found in the output images.")

if __name__ == "__main__":
    verify()
