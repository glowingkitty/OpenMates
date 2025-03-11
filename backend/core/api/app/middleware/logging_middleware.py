import time
import logging
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import json

from app.services.metrics import MetricsService

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, metrics_service: MetricsService):
        super().__init__(app)
        self.metrics_service = metrics_service
        
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Start timing
        start_time = time.time()
        
        # Extract request details for logging
        client_host = request.client.host if request.client else "unknown"
        method = request.method
        url = str(request.url)
        
        # Log request
        logger.info(
            f"Request started",
            extra={
                "request_id": request_id,
                "client_host": client_host,
                "method": method,
                "url": url,
                "event_type": "request_started"
            }
        )
        
        # Process request
        try:
            response = await call_next(request)
            status_code = response.status_code
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Track metrics
            endpoint = request.url.path
            self.metrics_service.track_api_request(method, endpoint, status_code)
            self.metrics_service.track_request_duration(method, endpoint, duration)
            
            # Log response
            logger.info(
                f"Request completed",
                extra={
                    "request_id": request_id,
                    "status_code": status_code,
                    "duration": duration,
                    "event_type": "request_completed"
                }
            )
            
            return response
            
        except Exception as e:
            # Calculate duration for failed requests
            duration = time.time() - start_time
            
            # Log exception
            logger.error(
                f"Request failed: {str(e)}",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "duration": duration,
                    "event_type": "request_failed"
                },
                exc_info=True
            )
            
            # Re-raise the exception
            raise
