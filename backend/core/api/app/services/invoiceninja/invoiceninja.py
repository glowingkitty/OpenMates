# backend/core/api/app/services/invoiceninja/invoiceninja.py
import requests
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

# Import the functions from submodules
import clients as client_ops
import invoices as invoice_ops
import payments as payment_ops
import transactions as transaction_ops # Corrected import for transactions
import bank_accounts as bank_account_ops # Import for bank account specific ops

logger = logging.getLogger(__name__)

# --- Configuration Placeholder ---
# In a real app, load this from environment variables, Vault, or a config file (e.g., using Pydantic)
@dataclass
class InvoiceNinjaConfig:
    INVOICE_NINJA_URL: str = os.getenv("SECRET__INVOICE_NINJA_URL") # TODO: Load externally
    API_TOKEN: str = os.getenv("SECRET__INVOICE_NINJA_SANDBOX_API_KEY") # TODO: Load externally
    USER_HASH_CUSTOM_FIELD: str = "9aDk1j2kDJDkhggkq" # TODO: Load externally
    ORDER_ID_CUSTOM_FIELD: str = "as1u2u2auasdha28Diasd" # TODO: Load externally

    # --- Names to search for in bank integrations ---
    # !! IMPORTANT !!: These names MUST match the 'bank_account_name' field
    #                  configured within Invoice Ninja for the respective integrations.
    REVOLUT_BANK_ACCOUNT_NAME: str = "Revolut Business Merchant"
    STRIPE_BANK_ACCOUNT_NAME: str = "Stripe"

    # --- Payment Type IDs (Still potentially useful, check if needed) ---
    PAYMENT_TYPE_ID_REVOLUT: Optional[str] = "16" # TODO: Load externally or make optional
    PAYMENT_TYPE_ID_STRIPE: Optional[str] = "16" # TODO: Load externally or make optional

    # Product keys could also be part of config if relatively static
    PRODUCT_KEY_CREDITS_1K: str = "1.000 credits"
    PRODUCT_KEY_CREDITS_10K: str = "10.000 credits"
    PRODUCT_KEY_CREDITS_21K: str = "21.000 credits"
    PRODUCT_KEY_CREDITS_54K: str = "54.000 credits"
    PRODUCT_KEY_CREDITS_110K: str = "110.000 credits"
    # ... other product keys ...

    # Default headers derived from the token
    headers: Dict[str, str] = field(init=False)

    def __post_init__(self):
        if not self.API_TOKEN or "YOUR_" in self.API_TOKEN:
             raise ValueError("Invoice Ninja API Token is not configured.")
        self.headers = {
            'X-API-TOKEN': self.API_TOKEN,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        }

# --- Main Service Class ---
class InvoiceNinjaService:
    def __init__(self, config: Optional[InvoiceNinjaConfig] = None):
        """
        Initializes the Invoice Ninja service client and fetches dynamic bank integration IDs.

        Args:
            config: An InvoiceNinjaConfig object. If None, a default config is created.
        """
        self.config = config or InvoiceNinjaConfig()
        self.headers = self.config.headers # Convenience access

        # --- Initialize dynamic bank integration details ---
        self._revolut_bank_account_id: Optional[str] = None
        self._revolut_bank_integration_id: Optional[str] = None # Note: API returns string ID for integration
        self._stripe_bank_account_id: Optional[str] = None
        self._stripe_bank_integration_id: Optional[str] = None # Note: API returns string ID for integration

        self._load_bank_integration_details()

    def _load_bank_integration_details(self):
        """Fetches bank integrations and stores IDs for configured account names."""
        logger.info("Attempting to load bank integration details from Invoice Ninja...")
        integrations = self.get_bank_integrations()

        if integrations is None:
            logger.error("Failed to retrieve bank integrations. Cannot determine bank account/integration IDs.")
            # Consider raising an exception here if these IDs are absolutely critical for startup
            return

        if not integrations:
            logger.warning("No bank integrations found in Invoice Ninja.")
            return

        found_revolut = False
        found_stripe = False

        revolut_target_name = self.config.REVOLUT_BANK_ACCOUNT_NAME.lower()
        stripe_target_name = self.config.STRIPE_BANK_ACCOUNT_NAME.lower()

        for integration in integrations:
            # Check required fields exist
            acc_name = integration.get('bank_account_name')
            acc_id = integration.get('bank_account_id')
            int_id = integration.get('id') # This is the Bank Integration Hashed ID

            if not acc_name or not int_id:
                logger.warning(f"Skipping integration due to missing data: {integration}")
                continue

            current_name_lower = acc_name.lower()

            # Check for Revolut
            if not found_revolut and current_name_lower == revolut_target_name:
                self._revolut_bank_account_id = acc_id
                self._revolut_bank_integration_id = int_id
                logger.info(f"Found Revolut integration: Name='{acc_name}', AccountID='{acc_id}', IntegrationID='{int_id}'")
                found_revolut = True

            # Check for Stripe
            if not found_stripe and current_name_lower == stripe_target_name:
                self._stripe_bank_account_id = acc_id
                self._stripe_bank_integration_id = int_id
                logger.info(f"Found Stripe integration: Name='{acc_name}', AccountID='{acc_id}', IntegrationID='{int_id}'")
                found_stripe = True

            # Optimization: exit early if both found
            if found_revolut and found_stripe:
                break

        # Log warnings if not found
        if not found_revolut:
            logger.warning(f"Could not find bank integration matching name '{self.config.REVOLUT_BANK_ACCOUNT_NAME}'. Revolut transactions cannot be processed.")
        if not found_stripe:
            logger.warning(f"Could not find bank integration matching name '{self.config.STRIPE_BANK_ACCOUNT_NAME}'. Stripe transactions cannot be processed.")

    def make_api_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Makes a standard JSON API request and handles common errors."""
        url = f"{self.config.INVOICE_NINJA_URL}/api/v1{endpoint}"
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self.headers, params=params, timeout=15)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=self.headers, params=params, data=json.dumps(data), timeout=15)
            elif method.upper() == 'PUT':
                 response = requests.put(url, headers=self.headers, params=params, data=json.dumps(data), timeout=15)
            else:
                logger.error(f"Unsupported HTTP method for JSON request: {method}")
                return None

            response.raise_for_status()
            # Handle potentially empty successful responses (e.g., 204 No Content)
            if response.status_code == 204 or not response.content:
                 return {} # Return empty dict for successful no-content responses
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"Error: Request timed out for {method} {url}")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err} - Status Code: {http_err.response.status_code}")
            try:
                error_details = http_err.response.json()
                logger.error(f"Error Details: {json.dumps(error_details, indent=2)}")
                # Specific check for the upload error mentioned
                if endpoint.endswith('/upload') and http_err.response.status_code == 404:
                     if "message" in error_details and "Method not supported" in error_details["message"]:
                          logger.error("Detected 'Method not supported' error on upload. Check API version/endpoint or if uploads require PUT.")
                     else:
                          logger.error("404 error on upload. Check invoice ID and endpoint path.")

            except json.JSONDecodeError:
                logger.error(f"Raw Error Response: {http_err.response.text}")
        except requests.exceptions.RequestException as req_err:
            logger.error(f"Other request error occurred: {req_err}")
        except json.JSONDecodeError:
            # This block might be less likely if raise_for_status catches errors first
            if 'response' in locals() and response and response.text:
                logger.error(f"Error: Failed to decode JSON response from {method} {url}")
                logger.error(f"Raw Response: {response.text}")
            else:
                 logger.error(f"Error: Empty or no response received from {method} {url}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred during API request: {e}")

        return None

    def _make_file_upload_request(self, endpoint: str, file_path: str) -> bool:
        """Handles file uploads using multipart/form-data."""
        url = f"{self.config.INVOICE_NINJA_URL}/api/v1{endpoint}"
        files = None
        try:
            # Use multipart/form-data for file uploads
            files = {'file': (os.path.basename(file_path), open(file_path, 'rb'), 'application/pdf')}

            # Create headers for upload, removing Content-Type for requests lib to set it
            upload_headers = self.headers.copy()
            if 'Content-Type' in upload_headers:
                del upload_headers['Content-Type']

            # Use POST as per original script (but see error note in make_api_request)
            response = requests.post(url, headers=upload_headers, files=files, timeout=30) # Longer timeout for uploads
            response.raise_for_status()
            # Assuming success if no exception is raised
            return True
        except requests.exceptions.HTTPError as http_err:
            # Log details within this specific context
            logger.error(f"HTTP error occurred uploading document: {http_err} - Status Code: {http_err.response.status_code}")
            try:
                error_details = http_err.response.json()
                logger.error(f"Upload Error Details: {json.dumps(error_details, indent=2)}")
                # Specific check for the 404 error
                if http_err.response.status_code == 404:
                     if "message" in error_details and "Method not supported" in error_details["message"]:
                          logger.error("Detected 'Method not supported' error on upload. Check API version/endpoint or if uploads require PUT.")
                     else:
                          logger.error("404 error on upload. Check invoice ID and endpoint path: %s", url)

            except json.JSONDecodeError:
                logger.error(f"Raw Upload Error Response: {http_err.response.text}")
            return False
        except Exception as e:
            logger.exception(f"An unexpected error occurred uploading document: {e}")
            return False
        finally:
            # Ensure the file handle is closed
            if files and 'file' in files and files['file'][1]:
                try:
                    files['file'][1].close()
                except Exception as e_close:
                    logger.error(f"Error closing file handle for {file_path}: {e_close}")


    # --- Client Operations ---
    def find_client_by_hash(self, user_hash: str) -> Optional[str]:
        return client_ops.find_client_by_hash(self, user_hash)

    def create_client(self, user_hash: str, external_order_id: str, client_details: Dict[str, Any]) -> Optional[str]:
        return client_ops.create_client(self, user_hash, external_order_id, client_details)

    # --- Invoice Operations ---
    def create_invoice(self, client_id: str, invoice_items: List[Dict[str, Any]], external_order_id: str) -> Tuple[Optional[str], Optional[str]]:
        return invoice_ops.create_invoice(self, client_id, invoice_items, external_order_id)

    def mark_invoice_sent(self, invoice_id: str) -> bool:
        # Note: This uses requests directly based on original script's PUT/POST logic.
        # Consider refactoring make_api_request if this pattern is common.
        return invoice_ops.mark_invoice_sent(self, invoice_id)

    def upload_invoice_document(self, invoice_id: str, pdf_file_path: str) -> bool:
        # Uses the dedicated _make_file_upload_request method
        return invoice_ops.upload_invoice_document(self, invoice_id, pdf_file_path)

    # --- Payment Operations ---
    def create_payment(self, invoice_id: str, client_id: str, amount: str | float, payment_date_str: str, external_order_id: str, payment_type_id: Optional[str] = None) -> Optional[str]:
        return payment_ops.create_payment(self, invoice_id, client_id, amount, payment_date_str, external_order_id, payment_type_id)

    # --- Bank Account Operations ---
    def create_bank_transaction(self, processor_bank_account_id: str, bank_integration_id: str, amount: str | float, date_str: str, invoice_number: str, external_order_id: str) -> Optional[str]:
        """
        Creates a bank transaction in Invoice Ninja.

        Args:
            processor_bank_account_id: The HASHED ID of the bank account (e.g., self._revolut_bank_account_id).
            bank_integration_id: The HASHED ID of the bank integration (e.g., self._revolut_bank_integration_id).
            amount: Transaction amount.
            date_str: Transaction date (YYYY-MM-DD).
            invoice_number: Associated Invoice Ninja invoice number.
            external_order_id: Your internal order ID.

        Returns:
            The HASHED ID of the created bank transaction, or None on failure.
        """
        # Calls the function from the transactions module now
        # IMPORTANT: Ensure the function signature in transactions.py expects string for bank_integration_id
        return transaction_ops.create_bank_transaction(self, processor_bank_account_id, bank_integration_id, amount, date_str, invoice_number, external_order_id)

    def get_bank_integrations(self, params: Optional[Dict[str, Any]] = None) -> Optional[List[Dict[str, Any]]]:
        """Retrieves bank integrations."""
        # Calls the function from the bank_accounts module now
        return bank_account_ops.get_bank_integrations(self, params)

    # --- Main Process Orchestration ---
    def process_income_transaction(
        self,
        processor_type: str, # 'revolut' or 'stripe'
        user_hash: str,
        external_order_id: str,
        client_data: Dict[str, Any],
        invoice_item_data: List[Dict[str, Any]], # List of {"product_key": "...", "quantity": ...}
        payment_amount: str | float,
        payment_date_str: str, # e.g., "YYYY-MM-DD"
        custom_pdf_path: Optional[str] = None # Path to the custom PDF to upload
        ) -> Optional[Dict[str, Any]]:
        """Handles the full workflow for processing an income transaction."""
        logger.info("=" * 40)
        logger.info(f"Starting Process for {processor_type.upper()} Order: {external_order_id} (User Hash: {user_hash})")

        # --- Determine Processor Specific IDs using fetched values ---
        target_processor_bank_id: Optional[str] = None
        target_bank_integration_id: Optional[str] = None # Use string now
        target_payment_type_id: Optional[str] = None

        if processor_type.lower() == 'revolut':
            target_processor_bank_id = self._revolut_bank_account_id
            target_bank_integration_id = self._revolut_bank_integration_id
            target_payment_type_id = self.config.PAYMENT_TYPE_ID_REVOLUT # Still from config if used
        elif processor_type.lower() == 'stripe':
            target_processor_bank_id = self._stripe_bank_account_id
            target_bank_integration_id = self._stripe_bank_integration_id
            target_payment_type_id = self.config.PAYMENT_TYPE_ID_STRIPE # Still from config if used
        else:
            logger.error(f"Invalid processor_type '{processor_type}'. Use 'revolut' or 'stripe'.")
            return None

        # --- Sanity Check Fetched IDs ---
        if not target_processor_bank_id:
             logger.error(f"Bank Account ID for {processor_type.upper()} was not found during initialization (looking for name: '{self.config.REVOLUT_BANK_ACCOUNT_NAME if processor_type.lower() == 'revolut' else self.config.STRIPE_BANK_ACCOUNT_NAME}'). Aborting.")
             return None
        if not target_bank_integration_id:
             logger.error(f"Bank Integration ID for {processor_type.upper()} was not found during initialization (looking for name: '{self.config.REVOLUT_BANK_ACCOUNT_NAME if processor_type.lower() == 'revolut' else self.config.STRIPE_BANK_ACCOUNT_NAME}'). Aborting.")
             return None

        # Check Payment Type ID from config (optional)
        if not target_payment_type_id or "YOUR_" in target_payment_type_id:
            logger.warning(f"Payment Type ID for {processor_type.upper()} is not configured correctly in config. Payment will be created without type.")
            target_payment_type_id = None # Allow process to continue

        # --- Find or Create Client ---
        ninja_client_id = self.find_client_by_hash(user_hash)
        if not ninja_client_id:
            ninja_client_id = self.create_client(user_hash, external_order_id, client_data)

        if not ninja_client_id:
            logger.critical("Could not find or create client. Aborting.")
            return None

        # --- Create Invoice ---
        ninja_invoice_id, ninja_invoice_number = self.create_invoice(ninja_client_id, invoice_item_data, external_order_id)

        if not ninja_invoice_id or not ninja_invoice_number:
            logger.error("Failed to create invoice. Aborting.")
            return None

        # --- Mark Invoice as Sent ---
        if not self.mark_invoice_sent(ninja_invoice_id):
            logger.warning("Failed to mark invoice as sent. Payment might remain unapplied initially.")
            # Continue processing

        # --- Upload Custom Document (if provided) ---
        pdf_upload_success = False
        if custom_pdf_path:
            pdf_upload_success = self.upload_invoice_document(ninja_invoice_id, custom_pdf_path)
            if not pdf_upload_success:
                logger.warning("Failed to upload custom PDF document.")
            # Continue process even if PDF upload fails

        # --- Create Payment ---
        ninja_payment_id = self.create_payment(
            invoice_id=ninja_invoice_id,
            client_id=ninja_client_id,
            amount=payment_amount,
            payment_date_str=payment_date_str,
            external_order_id=external_order_id,
            payment_type_id=target_payment_type_id # Use the potentially None value
        )

        if not ninja_payment_id:
            logger.error("Failed to create payment record. Invoice exists but payment step failed.")
            # Return partial success info? For now, return None
            return None

        # --- Create Bank Transaction ---
        # Pass the dynamically fetched IDs
        ninja_bank_transaction_id = self.create_bank_transaction(
            processor_bank_account_id=target_processor_bank_id, # Fetched dynamically
            bank_integration_id=target_bank_integration_id, # Fetched dynamically
            amount=payment_amount,
            date_str=payment_date_str,
            invoice_number=ninja_invoice_number,
            external_order_id=external_order_id
        )
        if not ninja_bank_transaction_id:
            logger.warning("Failed to create corresponding bank transaction record.")
            # Still consider the overall process potentially successful as payment was recorded

        # --- Success ---
        logger.info("=" * 40)
        logger.info(f"Process Completed Successfully for {processor_type.upper()} Order: {external_order_id}")
        result = {
            "processor": processor_type,
            "client_id": ninja_client_id,
            "invoice_id": ninja_invoice_id,
            "invoice_number": ninja_invoice_number,
            "payment_id": ninja_payment_id,
            "bank_transaction_id": ninja_bank_transaction_id, # Could be None if bank tx failed
            "pdf_upload_status": "Success" if pdf_upload_success else ("Skipped" if not custom_pdf_path else "Failed")
        }
        logger.info(f"Resulting IDs: {json.dumps(result, indent=2)}")
        logger.info("=" * 40)
        return result


if __name__ == "__main__":
    # Basic logging configuration for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Running InvoiceNinjaService for testing...")

    # Example usage:
    try:
        # Instantiate the service (uses default config from class)
        service = InvoiceNinjaService()

        # --- Dummy Data for Testing ---
        # Replace with actual test data as needed
        test_user_hash = "test_user_hash_123"
        test_external_order_id = "TEST_ORDER_XYZ_789"
        test_client_data = {
            "name": "Test Client",
            "email": "test.client@example.com",
            "address1": "123 Test St",
            "city": "Testville",
            "state": "TS",
            "postal_code": "12345",
            "country_id": "840" # USA
        }
        test_invoice_item_data = [
            {"product_key": service.config.PRODUCT_KEY_CREDITS_10K, "quantity": 1}
        ]
        test_payment_amount = 10.00 # Example amount
        test_payment_date_str = "2025-04-20" # Example date

        # --- Test Workflow ---

        # 1. Find or Create Client
        logger.info(f"Attempting to find or create client for user hash: {test_user_hash}")
        ninja_client_id = service.find_client_by_hash(test_user_hash)
        if not ninja_client_id:
            logger.info("Client not found, creating new client...")
            ninja_client_id = service.create_client(test_user_hash, test_external_order_id, test_client_data)

        if not ninja_client_id:
            logger.critical("Could not find or create client. Aborting test.")
            exit()
        logger.info(f"Client ID: {ninja_client_id}")

        # 2. Create Invoice
        logger.info(f"Attempting to create invoice for client ID: {ninja_client_id}")
        ninja_invoice_id, ninja_invoice_number = service.create_invoice(ninja_client_id, test_invoice_item_data, test_external_order_id)

        if not ninja_invoice_id or not ninja_invoice_number:
            logger.error("Failed to create invoice. Aborting test.")
            exit()
        logger.info(f"Invoice ID: {ninja_invoice_id}, Invoice Number: {ninja_invoice_number}")

        # 3. Mark Invoice as Sent (Optional but good practice)
        logger.info(f"Attempting to mark invoice {ninja_invoice_id} as sent...")
        if service.mark_invoice_sent(ninja_invoice_id):
            logger.info("Invoice marked as sent.")
        else:
            logger.warning("Failed to mark invoice as sent.")

        # 4. Create Payment
        logger.info(f"Attempting to create payment for invoice ID: {ninja_invoice_id}")
        # Using Revolut payment type ID for example, replace if needed
        payment_type_id = service.config.PAYMENT_TYPE_ID_REVOLUT
        ninja_payment_id = service.create_payment(
            invoice_id=ninja_invoice_id,
            client_id=ninja_client_id,
            amount=test_payment_amount,
            payment_date_str=test_payment_date_str,
            external_order_id=test_external_order_id,
            payment_type_id=payment_type_id
        )

        if not ninja_payment_id:
            logger.error("Failed to create payment record. Aborting test.")
            exit()
        logger.info(f"Payment ID: {ninja_payment_id}")

        # 5. Create Bank Transaction (Requires bank integration details to be loaded)
        logger.info("Attempting to create bank transaction...")
        # Using Revolut details for example, replace if needed
        processor_bank_account_id = service._revolut_bank_account_id
        bank_integration_id = service._revolut_bank_integration_id

        if processor_bank_account_id and bank_integration_id:
             ninja_bank_transaction_id = service.create_bank_transaction(
                processor_bank_account_id=processor_bank_account_id,
                bank_integration_id=bank_integration_id,
                amount=test_payment_amount,
                date_str=test_payment_date_str,
                invoice_number=ninja_invoice_number,
                external_order_id=test_external_order_id
            )
             if ninja_bank_transaction_id:
                 logger.info(f"Bank Transaction ID: {ninja_bank_transaction_id}")
             else:
                 logger.warning("Failed to create corresponding bank transaction record.")
        else:
            logger.warning("Skipping bank transaction creation: Bank integration details not loaded.")


        logger.info("Test workflow completed.")

    except ValueError as ve:
        logger.error(f"Configuration Error: {ve}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during test execution: {e}")

    logger.info("Testing finished.")
