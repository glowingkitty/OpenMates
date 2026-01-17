import asyncio
import logging
import os
import sys

# Add the workspace root to sys.path so we can import from backend
# The script will be at /home/superdev/projects/OpenMates/backend/scripts/test_fal_flux.py
# Workspace root is /home/superdev/projects/OpenMates
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

from backend.shared.providers.fal.flux import generate_image_fal_flux
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_fal_flux():
    secrets_manager = SecretsManager()
    # Mocking environment for Vault if needed, but docker exec should have it
    await secrets_manager.initialize()
    
    prompt = "A futuristic cyberpunk city with neon lights and flying cars, high detailed, 8k"
    
    try:
        logger.info("Starting fal.ai Flux test...")
        image_bytes = await generate_image_fal_flux(
            prompt=prompt,
            secrets_manager=secrets_manager
        )
        
        output_file = "/tmp/test_fal_flux.png"
        with open(output_file, "wb") as f:
            f.write(image_bytes)
        
        logger.info(f"Success! Image generated and saved to {output_file} ({len(image_bytes)} bytes)")
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
    finally:
        await secrets_manager.aclose()

if __name__ == "__main__":
    asyncio.run(test_fal_flux())
