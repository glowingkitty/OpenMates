import time
import logging
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.services.metrics import MetricsService

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp): 
        super().__init__(app)
        # Paths that should not be tracked at all
        self.exclude_paths = [
            "/metrics",
            "/health",
        ]
        
    async def dispatch(self, request: Request, call_next):
        # Add request ID to request state for potential use in handlers
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Skip metrics tracking for excluded paths
        path = request.url.path
        is_excluded = False
        for excluded in self.exclude_paths:
            if path.startswith(excluded):
                is_excluded = True
                break
                
        # Start timing for metrics
        start_time = time.time()
        
        # Extract method for metrics
        method = request.method
        
        # Process request - NO LOGGING AT ALL for normal requests
        try:
            response = await call_next(request)
            status_code = response.status_code
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Track metrics for non-excluded paths
            if not is_excluded:
                # Access metrics_service from request.app.state
                metrics_service = request.app.state.metrics_service 
                metrics_service.track_api_request(method, path, status_code)
                metrics_service.track_request_duration(method, path, duration)
            
            # ONLY log errors (status code >= 400) at WARNING level
            if status_code >= 400:
                logger.warning(
                    f"Request failed: {method} {path} - {status_code}",
                    extra={
                        "request_id": request_id,
                        "status_code": status_code,
                        "method": method,
                        "path": path,
                        "duration": duration,
                        "event_type": "request_error"
                    }
                )
            
            return response
            
        except Exception as e:
            # Log exceptions as errors
            logger.error(
                f"Request failed with exception: {method} {path} - {str(e)}",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "method": method,
                    "path": path,
                    "event_type": "request_exception"
                },
                exc_info=True
            )
            
            # Re-raise the exception
            raise
