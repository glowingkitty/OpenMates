# backend/core/api/app/middleware/logging_middleware.py
# This module defines a FastAPI middleware for logging HTTP requests and responses,
# including detailed error logging, client context, and metrics tracking.
# It ensures that response bodies are correctly handled and passed to the client
# even when inspected by the middleware.

import time
import logging
import uuid
import json # Added for parsing JSON response bodies
from typing import Optional # Added for type hinting
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
            response_from_handler = await call_next(request)
            status_code = response_from_handler.status_code

            # Read response body. This is necessary to inspect it and still send it to client.
            response_body_bytes = b""
            async for chunk in response_from_handler.body_iterator:
                response_body_bytes += chunk
            
            # Reconstruct the response to be returned.
            # This ensures the client receives the body after we've iterated over it.
            # Prepare headers and media_type for the new response
            # Safely create a dictionary from the response headers
            final_headers = {key.lower(): value for key, value in response_from_handler.headers.items()}
            final_media_type = response_from_handler.media_type

            # If the request is for the /metrics path and the original response
            # did not specify a Content-Type (hence media_type is None),
            # we set a default media_type of 'text/plain'.
            # Starlette's Response constructor will then add the appropriate
            # 'Content-Type: text/plain; charset=utf-8' header.
            if path == "/metrics/" and final_media_type is None:
                # Defensive check: ensure 'content-type' isn't somehow already in the dict
                # if media_type was None. This is unlikely with Starlette's Response behavior
                # but adds robustness.
                if not final_headers.get('content-type') and not final_headers.get('Content-Type'):
                    final_media_type = "text/plain"
            
            response_to_send = Response(
                content=response_body_bytes,
                status_code=status_code,
                headers=final_headers,
                media_type=final_media_type
            )

            duration = time.time() - start_time

            if not is_excluded:
                metrics_service = request.app.state.metrics_service
                metrics_service.track_api_request(method, path, status_code)
                metrics_service.track_request_duration(method, path, duration)

            if status_code >= 400:
                error_detail_str = None
                response_body_preview = None # For non-JSON or unparseable bodies

                content_type_header = response_to_send.headers.get("content-type", "").lower()
                if "application/json" in content_type_header:
                    try:
                        error_content = json.loads(response_body_bytes.decode('utf-8'))
                        if isinstance(error_content, dict) and "detail" in error_content:
                            detail_value = error_content["detail"]
                            if isinstance(detail_value, (str, int, float, bool)):
                                error_detail_str = str(detail_value)
                            else: # If detail is complex (e.g. dict or list), stringify it
                                error_detail_str = json.dumps(detail_value)
                        elif isinstance(error_content, dict):
                             error_detail_str = f"JSON response without 'detail' field: {json.dumps(error_content)[:200]}..." # Preview
                        else:
                             error_detail_str = f"JSON response is not a dict: {json.dumps(error_content)[:200]}..." # Preview
                    except (json.JSONDecodeError, UnicodeDecodeError) as json_exc:
                        error_detail_str = f"Failed to parse JSON response body: {str(json_exc)}"
                        response_body_preview = response_body_bytes[:256].decode(errors='replace')
                else:
                    error_detail_str = f"Response content-type ('{content_type_header}') not application/json or not present."
                    response_body_preview = response_body_bytes[:256].decode(errors='replace')
                
                headers_to_log = {
                    h_key: request.headers[h_key] for h_key in
                    ["user-agent", "referer", "accept", "content-type", "x-forwarded-for", "origin"]
                    if h_key in request.headers
                }
                auth_headers_present = {}
                if 'authorization' in request.headers:
                    auth_headers_present['authorization'] = True
                if 'cookie' in request.headers:
                    auth_headers_present['cookie'] = True
                
                log_message_parts = [f"Request failed: {method} {path} - {status_code}"]
                if error_detail_str and ("Failed to parse" in error_detail_str or "not application/json" in error_detail_str or "without 'detail' field" in error_detail_str or "not a dict" in error_detail_str) :
                    log_message_parts.append(f"Info: {error_detail_str}")
                elif error_detail_str:
                     log_message_parts.append(f"Detail: {error_detail_str}")

                final_log_message = " ".join(log_message_parts)

                extra_log_data = {
                    "request_id": request_id,
                    "status_code": status_code,
                    "method": method,
                    "path": path,
                    "duration": duration,
                    "event_type": "request_error",
                    "query_params": str(request.query_params) if request.query_params else None,
                    "request_headers_subset": headers_to_log if headers_to_log else None,
                    "auth_headers_present": auth_headers_present if auth_headers_present else None,
                }
                if response_body_preview:
                    extra_log_data["response_body_preview"] = response_body_preview
                
                logger.warning(final_log_message, extra=extra_log_data)
            
            return response_to_send
            
        except Exception as e:
            # Log exceptions as errors with more context
            extra_exception_data = {
                "request_id": request_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "method": method, # method and path are from the outer scope
                "path": path,   #
                "event_type": "request_exception",
            }
            if hasattr(request, 'query_params'): # Check if request attributes are safe to access
                extra_exception_data["query_params"] = str(request.query_params) if request.query_params else None
            if hasattr(request, 'headers'):
                 headers_subset = {
                    h_key: request.headers[h_key] for h_key in ["user-agent", "referer", "x-forwarded-for", "origin"]
                    if h_key in request.headers
                }
                 if headers_subset:
                    extra_exception_data["request_headers_subset"] = headers_subset

            logger.error(
                f"Request processing failed with unhandled exception: {method} {path} - {type(e).__name__}: {str(e)}",
                extra=extra_exception_data,
                exc_info=True # This provides the full traceback
            )
            # Re-raise the exception. FastAPI's default error handling will convert it
            # to a 500 Internal Server Error response.
            raise
