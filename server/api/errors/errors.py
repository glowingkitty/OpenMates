import logging
from fastapi import HTTPException
import os

# Set up logger
logger = logging.getLogger(__name__)

# List all custom errors here

class InvalidAPITokenError(HTTPException):
    def __init__(self, detail: str = "Invalid API token", log_message: str = None):
        super().__init__(status_code=401, detail=detail)
        self.log_message = log_message
        self._log_error()

    def _log_error(self):
        if self.log_message:
            logger.error(self.log_message)
        else:
            logger.exception("Unexpected error during API token validation")


class UserNotFoundError(HTTPException):
    def __init__(self, detail: str = "User not found", log_message: str = None):
        super().__init__(status_code=404, detail=detail)
        self.log_message = log_message
        self._log_error()

    def _log_error(self):
        if self.log_message:
            logger.error(self.log_message)
        else:
            logger.exception("Unexpected error during get user")


class InvalidPasswordError(HTTPException):
    def __init__(self, detail: str = "Invalid password", log_message: str = None):
        super().__init__(status_code=401, detail=detail)
        self.log_message = log_message
        self._log_error()

    def _log_error(self):
        if self.log_message:
            logger.error(self.log_message)
        else:
            logger.exception("Unexpected error during get user")