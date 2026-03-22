import io
import sys
import os

# Add the project root to sys.path to import our modules
sys.path.append(os.getcwd())

from backend.core.api.app.utils.image_processing import process_image_for_storage
from PIL import Image

def test_metadata_injection():
    print("Starting metadata injection test...")
    
    # 1. Create a dummy image
    img = Image.new('RGB', (100, 100), color='red')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    image_bytes = img_byte_arr.getvalue()
    
    # 2. Define metadata
    test_metadata = {
        "prompt": "A futuristic city test prompt",
        "model": "google/gemini-3-pro-image-preview",
        "software": "OpenMates Unit Test",
        "source": "OpenMates AI Test",
        "generated_at": "2026-01-20T12:00:00Z"
    }
    
    # 3. Process image
    print("Processing image...")
    results = process_image_for_storage(image_bytes, metadata=test_metadata)
    
    # 4. Verify results
    full_webp_bytes = results['full_webp']
    print(f"Full WEBP size: {len(full_webp_bytes)} bytes")
    
    # Load processed image and check for XMP
    processed_img = Image.open(io.BytesIO(full_webp_bytes))
    
    # Pillow 10+ stores XMP in info['xmp']
    xmp = processed_img.info.get('xmp')
    
    if xmp:
        print("SUCCESS: XMP metadata found in processed image.")
        xmp_str = xmp.decode('utf-8') if isinstance(xmp, bytes) else xmp
        
        # Check for key markers
        markers = [
            "trainedAlgorithmicMedia",
            "google/gemini-3-pro-image-preview",
            "A futuristic city test prompt",
            "OpenMates Unit Test"
        ]
        
        for marker in markers:
            if marker in xmp_str:
                print(f"  [OK] Found marker: {marker}")
            else:
                print(f"  [FAIL] Missing marker: {marker}")
    else:
        print("FAIL: No XMP metadata found in processed image.")
        print(f"Available info keys: {processed_img.info.keys()}")

if __name__ == "__main__":
    try:
        test_metadata_injection()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
