import os
import httpx
import logging
import time
import hmac
import hashlib
import json
from typing import Optional, Dict, Any, Tuple

from app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

class RevolutService:
    """
    Service for interacting with the Revolut Business Merchant API.
    Handles order creation and webhook verification.
    """

    def __init__(self, secrets_manager: SecretsManager):
        self.secrets_manager = secrets_manager
        self._client: Optional[httpx.AsyncClient] = None
        self.base_url: str = "" # Will be set during initialization

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create httpx client."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def _is_production(self) -> bool:
        """Check if the environment is production."""
        return os.getenv("SERVER_ENVIRONMENT", "development") == "production"

    async def initialize(self):
        """Set the base URL based on the environment."""
        if self._is_production():
            self.base_url = "https://merchant.revolut.com/api"
            logger.info("RevolutService initialized for PRODUCTION environment.")
        else:
            self.base_url = "https://sandbox-merchant.revolut.com/api"
            logger.info("RevolutService initialized for SANDBOX environment.")
        # Pre-fetch keys maybe? Or fetch on demand. Fetching on demand for now.

    async def _get_api_key(self) -> Optional[str]:
        """Retrieve the appropriate Revolut Secret API key from Secrets Manager."""
        key_name = (
            "API_SECRET__REVOLUT_BUSINESS_MERCHANT_PRODUCTION_SECRET_KEY"
            if self._is_production()
            else "API_SECRET__REVOLUT_BUSINESS_MERCHANT_SANDBOX_SECRET_KEY"
        )
        api_key = await self.secrets_manager.get_secret(key_name)
        if not api_key:
            logger.error(f"Revolut Secret Key '{key_name}' not found in Secrets Manager.")
        return api_key

    async def _get_webhook_secret(self) -> Optional[str]:
        """Retrieve the appropriate Revolut Webhook Signing Secret from Secrets Manager."""
        key_name = (
            "API_SECRET__REVOLUT_BUSINESS_MERCHANT_PRODUCTION_WEBHOOK_SECRET"
            if self._is_production()
            else "API_SECRET__REVOLUT_BUSINESS_MERCHANT_SANDBOX_WEBHOOK_SECRET"
        )
        secret = await self.secrets_manager.get_secret(key_name)
        if not secret:
            logger.error(f"Revolut Webhook Secret '{key_name}' not found in Secrets Manager.")
        return secret

    async def create_order(
        self,
        amount: int,
        currency: str,
        email: str,
        user_id: str,
        credits_amount: int
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a payment order with Revolut.

        Args:
            amount: Amount in the smallest currency unit (e.g., cents).
            currency: 3-letter ISO currency code (e.g., "EUR").
            email: Customer's email address.
            user_id: Internal user ID for tracking.
            credits_amount: Number of credits being purchased (for metadata).

        Returns:
            A dictionary containing the order details from Revolut API, 
            including the 'token', or None if an error occurred.
        """
        api_key = await self._get_api_key()
        if not api_key:
            return None # Error logged in _get_api_key

        if not self.base_url:
            await self.initialize() # Ensure base_url is set

        client = await self._get_client()
        url = f"{self.base_url}/orders"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Revolut-Api-Version": "2024-09-01",
        }
        
        # Construct a unique reference for the merchant order
        timestamp = int(time.time())
        merchant_order_ref = f"user_{user_id}_credits_{credits_amount}_{timestamp}"

        payload = {
            "amount": amount,
            "currency": currency,
            "capture_mode": "automatic", # Fixed: must be lowercase per Revolut API docs
            "merchant_order_ext_ref": merchant_order_ref,
            "email": email,
            "metadata": {
                "user_id": str(user_id), # Ensure user_id is string if needed by Directus later
                "credits_purchased": str(credits_amount),
                "purchase_type": "credits",
                "timestamp_created": str(timestamp)
            }
        }

        try:
            logger.info(f"Creating Revolut order for user {user_id}. Amount: {amount} {currency}")
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()  # Raise exception for 4xx/5xx status codes
            order_data = response.json()
            logger.info(f"Revolut order created successfully. Order ID: {order_data.get('id')}, Token: {order_data.get('token')}")
            return order_data
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error creating Revolut order: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error creating Revolut order: {str(e)}", exc_info=True)
            return None

    async def verify_and_parse_webhook(
        self, payload_bytes: bytes, signature_header: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Verifies the Revolut webhook signature and parses the payload.

        Args:
            payload_bytes: The raw request body bytes.
            signature_header: The value of the 'Revolut-Signature' header.

        Returns:
            A tuple: (is_valid: bool, parsed_payload: Optional[Dict[str, Any]]).
            Returns (False, None) if signature is missing or invalid.
            Returns (True, parsed_payload) if signature is valid.
            Returns (True, None) if signature is valid but JSON parsing fails.
        """
        if not signature_header:
            logger.warning("Webhook verification failed: Missing Revolut-Signature header.")
            return False, None

        webhook_secret = await self._get_webhook_secret()
        if not webhook_secret:
            logger.error("Webhook verification failed: Webhook signing secret not configured.")
            return False, None # Cannot verify without the secret

        # Parse the signature header (e.g., "t=1678886400,v1=...")
        # For simplicity, assuming a basic format. Revolut might have a more complex one.
        # A robust implementation should parse timestamp and signatures properly.
        # This example assumes a simple HMAC-SHA256 signature. Adapt if needed.
        # Example structure: t=<timestamp>,v1=<signature>
        parts = {p.split('=')[0]: p.split('=')[1] for p in signature_header.split(',')}
        request_timestamp_str = parts.get('t')
        request_signature = parts.get('v1')

        if not request_timestamp_str or not request_signature:
             logger.warning(f"Webhook verification failed: Could not parse signature header: {signature_header}")
             return False, None

        # Optional: Check timestamp tolerance to prevent replay attacks
        try:
            request_timestamp = int(request_timestamp_str)
            current_timestamp = int(time.time())
            tolerance = 300 # 5 minutes tolerance
            if abs(current_timestamp - request_timestamp) > tolerance:
                logger.warning(f"Webhook verification failed: Timestamp outside tolerance. Request: {request_timestamp}, Current: {current_timestamp}")
                # return False, None # Decide if you want to enforce this strictly
        except ValueError:
             logger.warning(f"Webhook verification failed: Invalid timestamp format in header: {request_timestamp_str}")
             return False, None


        # Construct the signed payload string: timestamp + '.' + request_body
        signed_payload = f"{request_timestamp_str}.{payload_bytes.decode('utf-8')}"

        # Calculate the expected signature
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Compare signatures securely
        if not hmac.compare_digest(expected_signature, request_signature):
            logger.error(f"Webhook verification failed: Signature mismatch. Expected: {expected_signature}, Got: {request_signature}")
            return False, None

        logger.info("Revolut webhook signature verified successfully.")

        # Try parsing the payload
        try:
            parsed_payload = json.loads(payload_bytes)
            return True, parsed_payload
        except json.JSONDecodeError as e:
            logger.error(f"Webhook signature valid, but failed to parse JSON payload: {str(e)}")
            return True, None # Signature was valid, but payload is unusable

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the details of a specific order from Revolut.

        Args:
            order_id: The ID of the order to retrieve.

        Returns:
            A dictionary containing the order details, or None if an error occurred.
        """
        api_key = await self._get_api_key()
        if not api_key:
            return None

        if not self.base_url:
            await self.initialize()

        client = await self._get_client()
        url = f"{self.base_url}/orders/{order_id}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Revolut-Api-Version": "2024-09-01", # Use consistent API version
        }

        try:
            logger.info(f"Retrieving Revolut order details for Order ID: {order_id}")
            response = await client.get(url, headers=headers)
            
            # Handle 404 specifically
            if response.status_code == 404:
                 logger.warning(f"Revolut order {order_id} not found.")
                 return None
                 
            response.raise_for_status() # Raise for other 4xx/5xx errors
            order_data = response.json()
            logger.info("Full order_data:")
            logger.info(order_data) # Log the full order data for debugging
            logger.info(f"Successfully retrieved details for Revolut order {order_id}. State: {order_data.get('state')}")
            return order_data
        except httpx.HTTPStatusError as e:
            # Log specific HTTP errors (other than 404 handled above)
            logger.error(f"HTTP error retrieving Revolut order {order_id}: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving Revolut order {order_id}: {str(e)}", exc_info=True)
            return None

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("RevolutService HTTP client closed.")