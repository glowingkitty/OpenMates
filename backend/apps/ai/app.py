# backend/apps/ai/app.py
# Main application file for the AI App.

import os
import logging
import uvicorn
# Removed HTTPException, Pydantic models, List, Dict, Any, Optional as they are now in ask_skill.py
# Removed celery_app import as AskSkill handles task dispatch

from apps.base_app import BaseApp # Import BaseApp from the /app/apps directory

# Configure logging for the AI app
logger = logging.getLogger(__name__)
# Basic logging configuration, can be enhanced
logging.basicConfig(level=os.getenv("AI_APP_LOG_LEVEL", "INFO").upper())


# Pydantic models for /skill/ask endpoint are now defined in backend/apps/ai/skills/ask_skill.py
# class AskSkillRequest(BaseModel): ...
# class AskSkillResponse(BaseModel): ...


APP_DIR = os.path.dirname(os.path.abspath(__file__))
# The port the app's FastAPI server listens on *inside its container*.
# This should match the 'port' in backend_config.yml for this app.
APP_PORT = int(os.getenv("AI_APP_INTERNAL_PORT", "8000"))

class AIApp(BaseApp):
    """
    The main AI Application class.
    It will handle AI-specific logic, skills, and focuses.
    """
    def __init__(self, app_dir: str, app_yml_filename: str = "app.yml", app_port: int = 8000):
        # The app_id will be derived from app_dir (e.g., 'ai') if not in app.yml
        super().__init__(app_dir, app_yml_filename, app_port)
        logger.info(f"AIApp '{self.name}' (ID: {self.id}) initialized. Running on port {self.port}. Valid: {self.is_valid}")
        self._register_ai_specific_routes()

    def _register_ai_specific_routes(self):
        """Registers FastAPI routes specific to the AI App."""
        
        @self.fastapi_app.get("/ai-status", tags=["AI App Specific"])
        async def get_ai_status():
            """Returns the status of the AI App."""
            return {"status": "AI App is running", "app_id": self.id, "app_name": self.name}

        # The /skill/ask endpoint is now handled by the AskSkill class,
        # which is discovered and routed automatically by BaseApp via app.yml.
        # No need to define it explicitly here.
        # @self.fastapi_app.post("/skill/ask", response_model=AskSkillResponse, tags=["AI Skills"]) ...

        logger.info("AI-specific routes registered. /skill/ask will be auto-registered by BaseApp if defined in app.yml.")


# Create an instance of the AIApp
# The app_dir is the directory where this app.py file is located.
ai_app_instance = AIApp(app_dir=APP_DIR, app_port=APP_PORT)

# Expose the FastAPI app instance for Uvicorn
app = ai_app_instance.fastapi_app

if __name__ == "__main__":
    logger.info(f"Starting AI App directly using Uvicorn on port {APP_PORT}...")
    # Ensure the app instance used by uvicorn is the one from this file.
    uvicorn.run("app:app", host="0.0.0.0", port=APP_PORT, reload=True if os.getenv("AI_APP_RELOAD") else False)