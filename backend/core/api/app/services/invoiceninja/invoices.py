# backend/core/api/app/services/invoiceninja/invoices.py
import logging
import os
import json
import requests # Keep requests import for exception handling
from typing import Optional, List, Dict, Any, Tuple

# Note: These functions are intended to be part of the InvoiceNinjaService class.
# They expect 'service_instance' (representing 'self') to provide:
# - service_instance.config (with attributes like INVOICE_NINJA_URL)
# - service_instance.headers
# - service_instance.make_api_request(method, endpoint, params=None, data=None)
# - service_instance._make_file_upload_request(endpoint, file_path) # A dedicated method for file uploads

logger = logging.getLogger(__name__)


def create_invoice(
        service_instance: Any, 
        client_id: str, 
        invoice_items: List[Dict[str, Any]],
        invoice_date: str,
        due_date: str,
        payment_processor: str,
        external_order_id: str, 
        custom_invoice_number: Optional[str] = None,
        mark_sent: bool = True
        ) -> Tuple[Optional[str], Optional[str]]:
    """
    Creates a new invoice using product_keys for items.

    Args:
        service_instance: The instance of the main service class.
        client_id: The ID of the client to create the invoice for.
        invoice_items: A list of dictionaries, each with "product_key" and "quantity".
        external_order_id: The external order ID for reference.
        custom_invoice_number: Optional custom number for the invoice.

    Returns:
        A tuple containing the new invoice ID and invoice number if successful, otherwise (None, None).
    """
    logger.info(f"Attempting to create invoice for client ID {client_id}...")
    if not invoice_items:
        logger.error("Cannot create invoice without items.")
        return None, None

    # Calculate total amount and ensure items have necessary keys
    total_amount = 0.0
    for item in invoice_items:
        if "product_key" not in item or "quantity" not in item or "cost" not in item:
            logger.error(f"Invoice item missing 'product_key', 'quantity', or 'cost': {item}")
            return None, None
        try:
            quantity = float(item.get("quantity", 0))
            cost = float(item.get("cost", 0))
            total_amount += quantity * cost
        except (ValueError, TypeError) as e:
            logger.error(f"Error calculating total amount for item {item}: {e}")
            return None, None
    logger.info(f"Calculated total invoice amount: {total_amount}")

    payload = {
        "client_id": client_id,
        "line_items": invoice_items,
        "date": invoice_date,
        "due_date": due_date,
        "custom_value1": payment_processor,
        "custom_value2": external_order_id,
        "private_notes": f"{payment_processor} Order ID: {external_order_id}"
    }
    if custom_invoice_number:
        payload["number"] = custom_invoice_number

    # Mark as sent during creation using query parameter.
    query_params = {"mark_sent": mark_sent}

    response_data = service_instance.make_api_request('POST', '/invoices', params=query_params, data=payload)

    if response_data is not None and 'data' in response_data:
        new_invoice = response_data['data']
        invoice_id = new_invoice.get('id')
        invoice_number = new_invoice.get('number', 'N/A')
        if invoice_id:
            # Log the correct status based on mark_sent parameter
            status_text = "Sent (processed)" if mark_sent else "Draft"
            logger.info(f"Successfully created invoice ({status_text}): ID={invoice_id}, Number={invoice_number}")
            return invoice_id, invoice_number
        else:
            logger.error("Invoice creation response did not contain an ID.")
            return None, None
    else:
        logger.error("Failed to create invoice.")
        return None, None


def upload_invoice_document(service_instance: Any, invoice_id: str, pdf_data: bytes, filename: str) -> bool:
    """
    Uploads a custom PDF document (from bytes) to an existing invoice.

    Args:
        service_instance: The instance of the main service class.
        invoice_id: The ID of the invoice to upload the document to.
        pdf_data: The PDF file content as bytes.
        filename: The desired filename for the uploaded document.

    Returns:
        True if successful, False otherwise.
    """
    logger.info(f"Attempting to upload document '{filename}' (from bytes) to invoice ID {invoice_id}...")

    endpoint = f'/invoices/{invoice_id}/upload'

    # Delegate the actual file upload mechanism to the service instance
    # This allows the service to handle headers and multipart logic correctly.
    # The service method should return True/False based on success.
    # We pass the endpoint, byte data, and filename.
    success = service_instance._make_file_upload_request(endpoint, pdf_data, filename)

    if success:
        logger.info(f"Successfully uploaded document to invoice ID {invoice_id}.")
    else:
        # Error logging should happen within _make_file_upload_request
        logger.error(f"Failed to upload document to invoice ID {invoice_id}.")

    return success