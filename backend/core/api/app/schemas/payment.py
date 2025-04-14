from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

# --- Request Models ---

class CreateOrderRequest(BaseModel):
    """Request body for creating a payment order."""
    amount: int = Field(..., description="Amount in the smallest currency unit (e.g., cents). Must be positive.")
    currency: str = Field(..., min_length=3, max_length=3, description="3-letter ISO currency code (e.g., 'EUR').")
    credits_amount: int = Field(..., description="The number of credits being purchased. Must be positive.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "amount": 2000, # e.g., 20 EUR
                    "currency": "EUR",
                    "credits_amount": 21000
                }
            ]
        }
    }

# --- Response Models ---

class PaymentConfigResponse(BaseModel):
    """Response containing public configuration for the frontend."""
    revolut_public_key: str = Field(..., description="The public API key for Revolut Checkout Widget.")
    environment: str = Field(..., description="The environment ('production' or 'sandbox').")

class CreateOrderResponse(BaseModel):
    """Response containing the token needed to initialize the Revolut Checkout Widget."""
    order_token: str = Field(..., description="The public token associated with the created Revolut order.")

# --- Webhook Models (Optional but good practice for validation) ---
# These might need adjustment based on the actual webhook payload structure from Revolut

class RevolutWebhookMetadata(BaseModel):
    user_id: Optional[str] = None
    credits_purchased: Optional[str] = None
    purchase_type: Optional[str] = None
    timestamp_created: Optional[str] = None
    # Add any other custom metadata fields you send

class RevolutWebhookOrderData(BaseModel):
    id: str
    state: str
    amount: Optional[int] = None # Amount might not always be present depending on event
    currency: Optional[str] = None
    metadata: Optional[RevolutWebhookMetadata] = None
    error_message: Optional[str] = None # Present on ORDER_FAILED
    # Add other relevant fields from Revolut's webhook payload

class RevolutWebhookPayload(BaseModel):
    event: str # e.g., "ORDER_COMPLETED", "ORDER_FAILED"
    data: RevolutWebhookOrderData