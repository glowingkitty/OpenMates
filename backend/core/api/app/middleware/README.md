# backend/core/api/app/middleware/README.md

This folder contains custom FastAPI middleware used in the application.
Middleware components intercept requests and responses to perform cross-cutting concerns
such as logging, authentication, metrics collection, or header manipulation.

Files:
- [`logging_middleware.py`](logging_middleware.py): Implements `LoggingMiddleware` for comprehensive request/response logging. It captures standard request/response data, detailed error information (including response body details for errors), client information, and performance metrics. It also enhances logging for unhandled exceptions during request processing.