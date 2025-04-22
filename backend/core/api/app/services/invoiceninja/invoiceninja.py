# backend/core/api/app/services/invoiceninja/invoiceninja.py
import requests
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from datetime import date # Added for payment date

# Assuming SecretsManager is accessible via this relative path
# Adjust the import path if necessary based on your project structure
from app.utils.secrets_manager import SecretsManager

# Import the functions from submodules
from app.services.invoiceninja import clients, invoices, payments, bank_accounts

logger = logging.getLogger(__name__)

class InvoiceNinjaService:
    """
    Service class for interacting with the Invoice Ninja API.

    Use the async class method `create` to instantiate this service,
    as initialization requires fetching secrets asynchronously.
    Example:
        secrets_manager = SecretsManager(...)
        invoice_ninja_service = await InvoiceNinjaService.create(secrets_manager)
    """
    def __init__(self, secrets_manager: SecretsManager):
        """
        Initializes the Invoice Ninja service client minimally.
        Asynchronous initialization is handled by the `create` class method.

        Args:
            secrets_manager: An instance of the SecretsManager.
        """
        self.secrets_manager = secrets_manager
        self.INVOICE_NINJA_URL: Optional[str] = None
        self.API_TOKEN: Optional[str] = None
        self.headers: Optional[Dict[str, str]] = None

        # --- Static Configuration (Consider moving to config or secrets) ---
        self.REVOLUT_BANK_ACCOUNT_NAME: str = "Revolut Business Merchant"
        self.STRIPE_BANK_ACCOUNT_NAME: str = "Stripe"
        self.PAYMENT_TYPE_ID_REVOLUT: Optional[str] = "16" # TODO: Load externally or make optional
        self.PAYMENT_TYPE_ID_STRIPE: Optional[str] = "16" # TODO: Load externally or make optional
        self.PRODUCT_KEY_CREDITS_1K: str = "1.000 credits"
        self.PRODUCT_KEY_CREDITS_10K: str = "10.000 credits"
        self.PRODUCT_KEY_CREDITS_21K: str = "21.000 credits"
        self.PRODUCT_KEY_CREDITS_54K: str = "54.000 credits"
        self.PRODUCT_KEY_CREDITS_110K: str = "110.000 credits"
        self.USER_HASH_CUSTOM_FIELD: str = "custom_value1" # Field used to store user hash
        self.ORDER_ID_CUSTOM_FIELD: str = "custom_value2" # Field used to store external order ID

        # --- Initialize dynamic bank integration details (will be populated in _async_init) ---
        self._revolut_bank_account_id: Optional[str] = None
        self._revolut_bank_integration_id: Optional[str] = None # Note: API returns string ID for integration
        self._stripe_bank_account_id: Optional[str] = None
        self._stripe_bank_integration_id: Optional[str] = None # Note: API returns string ID for integration

        # Initialization requiring secrets is deferred to _async_init

    async def _async_init(self):
        """Performs asynchronous initialization steps after secrets are fetched."""
        logger.info("Performing async initialization for InvoiceNinjaService...")
        self.INVOICE_NINJA_URL = await self.secrets_manager.get_secret("SECRET__INVOICE_NINJA_URL")
        self.API_TOKEN = await self.secrets_manager.get_secret("SECRET__INVOICE_NINJA_SANDBOX_API_KEY") # Using SANDBOX key as requested

        if not self.INVOICE_NINJA_URL:
            logger.error("Invoice Ninja URL could not be retrieved from Secrets Manager.")
            raise ValueError("Invoice Ninja URL could not be retrieved from Secrets Manager.")
        if not self.API_TOKEN:
            logger.error("Invoice Ninja API Token could not be retrieved from Secrets Manager.")
            raise ValueError("Invoice Ninja API Token could not be retrieved from Secrets Manager.")

        logger.info("Invoice Ninja URL and API Token retrieved successfully.")

        self.headers = {
            'X-API-TOKEN': self.API_TOKEN,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        }

        # Now load bank details which requires API access (and thus headers)
        # Note: _load_bank_integration_details uses synchronous requests.
        # This might block the event loop. Consider making it async in the future.
        self._load_bank_integration_details()
        logger.info("Async initialization for InvoiceNinjaService complete.")


    @classmethod
    async def create(cls, secrets_manager: SecretsManager) -> 'InvoiceNinjaService':
        """
        Asynchronously creates and initializes an instance of InvoiceNinjaService.

        Args:
            secrets_manager: An instance of the SecretsManager.

        Returns:
            A fully initialized InvoiceNinjaService instance.
        """
        instance = cls(secrets_manager)
        await instance._async_init()
        return instance

    def _load_bank_integration_details(self):
        """Fetches bank integrations and stores IDs for configured account names."""
        # Ensure headers are set before making API calls
        if not self.headers:
            logger.error("Cannot load bank integration details: Headers not initialized.")
            # Or raise an exception, depending on desired behavior
            # raise RuntimeError("Headers not initialized before loading bank details.")
            return

        logger.info("Attempting to load bank integration details from Invoice Ninja...")
        integrations = self.get_bank_integrations()

        if integrations is None:
            logger.error("Failed to retrieve bank integrations. Cannot determine bank account/integration IDs.")
            # Consider raising an exception here if these IDs are absolutely critical for startup
            return

        if not integrations:
            logger.warning("No bank integrations found in Invoice Ninja.")
            return
        else:
            # Add detailed logging for received integrations
            logger.debug(f"Received {len(integrations)} bank integrations from API: {json.dumps(integrations, indent=2)}")


        found_revolut = False
        found_stripe = False

        for integration in integrations:
            # Check required fields exist
            acc_name = integration.get('bank_account_name')
            acc_id = integration.get('bank_account_id') # Bank Account Hashed ID
            int_id = integration.get('id') # Bank Integration Hashed ID

            # --- Enhanced Check: Ensure all required IDs are present (not None) ---
            # We check for None explicitly because bank_account_id can be 0, which is falsy but valid.
            if acc_name is None or acc_id is None or int_id is None:
                logger.warning(f"Skipping integration due to missing required data (Name is None, AccountID is None, or IntegrationID is None): {integration}")
                continue

            logger.debug(f"Processing integration: Name='{acc_name}', AccountID='{acc_id}', IntegrationID='{int_id}'")

            # Check for Revolut
            if not found_revolut and acc_name == self.REVOLUT_BANK_ACCOUNT_NAME:
                self._revolut_bank_account_id = acc_id
                self._revolut_bank_integration_id = int_id
                logger.info(f"Found and assigned Revolut integration: Name='{acc_name}', AccountID='{self._revolut_bank_account_id}', IntegrationID='{self._revolut_bank_integration_id}'")
                found_revolut = True

            # Check for Stripe
            if not found_stripe and acc_name == self.STRIPE_BANK_ACCOUNT_NAME:
                self._stripe_bank_account_id = acc_id
                self._stripe_bank_integration_id = int_id
                logger.info(f"Found and assigned Stripe integration: Name='{acc_name}', AccountID='{self._stripe_bank_account_id}', IntegrationID='{self._stripe_bank_integration_id}'")
                found_stripe = True

            # Optimization: exit early if both found
            if found_revolut and found_stripe:
                logger.debug("Found both Revolut and Stripe integrations. Stopping search.")
                break

        # Log warnings if not found
        if not found_revolut:
            logger.warning(f"Could not find a valid bank integration matching name '{self.REVOLUT_BANK_ACCOUNT_NAME}' with all required IDs. Revolut transactions cannot be processed.")
        if not found_stripe:
            logger.warning(f"Could not find a valid bank integration matching name '{self.STRIPE_BANK_ACCOUNT_NAME}' with all required IDs. Stripe transactions cannot be processed.")

    def make_api_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Makes a standard JSON API request and handles common errors."""
        url = f"{self.INVOICE_NINJA_URL}/api/v1{endpoint}"
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

    def _make_file_upload_request(self, endpoint: str, file_data: bytes, filename: str) -> bool:
        """Handles file uploads using multipart/form-data from byte data."""
        url = f"{self.INVOICE_NINJA_URL}/api/v1{endpoint}"
        files = None
        try:
            # Use multipart/form-data for file uploads from bytes
            files = {'file': (filename, file_data, 'application/pdf')}

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
        return clients.find_client_by_hash(self, user_hash)

    def create_client(self, user_hash: str, external_order_id: str, client_details: Dict[str, Any]) -> Optional[str]:
        return clients.create_client(self, user_hash, external_order_id, client_details)

    # --- Invoice Operations ---
    def create_invoice(self, client_id: str, invoice_items: List[Dict[str, Any]], external_order_id: str) -> Tuple[Optional[str], Optional[str]]:
        return invoices.create_invoice(self, client_id, invoice_items, external_order_id)

    def mark_invoice_sent(self, invoice_id: str) -> bool:
        # Note: This uses requests directly based on original script's PUT/POST logic.
        # Consider refactoring make_api_request if this pattern is common.
        return invoices.mark_invoice_sent(self, invoice_id)

    def upload_invoice_document(self, invoice_id: str, pdf_data: bytes, filename: str) -> bool:
        # Uses the dedicated _make_file_upload_request method
        # Assuming invoices.upload_invoice_document is updated to accept bytes and filename
        return invoices.upload_invoice_document(self, invoice_id, pdf_data, filename)

    # --- Payment Operations ---
    def create_payment(self, invoice_id: str, client_id: str, amount: float, payment_date_str: str, external_order_id: str, payment_type_id: Optional[str] = None) -> Optional[str]:
        return payments.create_payment(self, invoice_id, client_id, amount, payment_date_str, external_order_id, payment_type_id)

    # --- Bank Account Operations ---
    def create_bank_transaction(self, processor_bank_account_id: str, bank_integration_id: str, amount: float, date_str: str, invoice_number: str, external_order_id: str) -> Optional[str]:
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
        return transactions.create_bank_transaction(self, processor_bank_account_id, bank_integration_id, amount, date_str, invoice_number, external_order_id)

    def get_bank_integrations(self, params: Optional[Dict[str, Any]] = None) -> Optional[List[Dict[str, Any]]]:
        """Retrieves bank integrations."""
        # Calls the function from the bank_accounts module now
        return bank_accounts.get_bank_integrations(self, params)

    # --- Main Process Orchestration ---
    def process_income_transaction(
        self,
        user_hash: str,
        external_order_id: str,
        customer_firstname: str,
        customer_lastname: str,
        credits_value: int,
        purchase_price_value: float, # Direct price input
        # payment_date_str is now auto-generated
        custom_pdf_data: Optional[bytes] = None, # PDF data as bytes
        processor_type: str = "revolut" # 'revolut' or 'stripe'
        ) -> Optional[Dict[str, Any]]:
        """
        Handles the full workflow for processing an income transaction,
        using a directly provided purchase price.
        """
        logger.info("=" * 40)
        logger.info(f"Starting Process for {processor_type.upper()} Order: {external_order_id} (User Hash: {user_hash})")

        # --- Auto-generate Payment Date ---
        payment_date_str = date.today().strftime('%Y-%m-%d')
        logger.info(f"Using payment date: {payment_date_str}")

        # --- Use provided price directly ---
        payment_amount = purchase_price_value
        logger.info(f"Using provided purchase price: {payment_amount}")

        # --- Determine Processor Specific IDs using fetched values ---
        target_processor_bank_id: Optional[str] = None
        target_bank_integration_id: Optional[str] = None
        target_payment_type_id: Optional[str] = None

        if processor_type.lower() == 'revolut':
            target_processor_bank_id = self._revolut_bank_account_id
            target_bank_integration_id = self._revolut_bank_integration_id
            target_payment_type_id = self.PAYMENT_TYPE_ID_REVOLUT
        elif processor_type.lower() == 'stripe':
            target_processor_bank_id = self._stripe_bank_account_id
            target_bank_integration_id = self._stripe_bank_integration_id
            target_payment_type_id = self.PAYMENT_TYPE_ID_STRIPE
        else:
            logger.warning(f"Unknown processor type '{processor_type}'. Cannot determine bank/integration IDs.")
            # Decide if you should abort or continue without bank details

        # --- Log Determined IDs Before Check ---
        logger.info(f"Attempting to use IDs for processor '{processor_type}': BankAccountID='{target_processor_bank_id}', BankIntegrationID='{target_bank_integration_id}', PaymentTypeID='{target_payment_type_id}'")

        # --- Sanity Check Fetched IDs ---
        if target_processor_bank_id is None:
            logger.error(f"Bank Account ID for the processor type '{processor_type}' was not found or assigned during initialization. Aborting.")
            return None
        if target_bank_integration_id is None:
            logger.error(f"Bank Integration ID for the processor type '{processor_type}' was not found or assigned during initialization. Aborting.")
            return None
    
        # --- Find or Create Client ---
        ninja_client_id = self.find_client_by_hash(user_hash)
        if not ninja_client_id:
            client_details = {
                "first_name": customer_firstname,
                "last_name": customer_lastname,
                "custom_value1": user_hash,
                "custom_value2": external_order_id
            }
            logger.info(f"Client not found by hash '{user_hash}'. Creating new client...")
            ninja_client_id = self.create_client(user_hash, external_order_id, client_details)

        if not ninja_client_id:
            logger.critical("Could not find or create client. Aborting.")
            return None
        else:
             logger.info(f"Using Client ID: {ninja_client_id}")

        # --- Determine Product Key based on credits_value ---
        product_key: Optional[str] = None
        if credits_value == 1000:
            product_key = self.PRODUCT_KEY_CREDITS_1K
        elif credits_value == 10000:
            product_key = self.PRODUCT_KEY_CREDITS_10K
        elif credits_value == 21000:
            product_key = self.PRODUCT_KEY_CREDITS_21K
        elif credits_value == 54000:
            product_key = self.PRODUCT_KEY_CREDITS_54K
        elif credits_value == 110000:
            product_key = self.PRODUCT_KEY_CREDITS_110K
        else:
            logger.error(f"Invalid credits_value '{credits_value}'. Cannot determine product key for invoice line item. Aborting.")
            return None
        logger.info(f"Selected product key for invoice line item (based on credits {credits_value}): {product_key}")

        # Prepare invoice items (using determined product key and provided price)
        invoice_item_data = [
            {
                "product_key": product_key,
                "quantity": 1,
                "cost": purchase_price_value # Use the provided price for the line item cost
            }
        ]

        # --- Create Invoice ---
        logger.info(f"Creating invoice for Client ID: {ninja_client_id} with items: {invoice_item_data}")
        ninja_invoice_id, ninja_invoice_number = self.create_invoice(ninja_client_id, invoice_item_data, external_order_id)

        if not ninja_invoice_id or not ninja_invoice_number:
            logger.error("Failed to create invoice. Aborting.")
            return None
        else:
             logger.info(f"Invoice created: ID={ninja_invoice_id}, Number={ninja_invoice_number}")

        # --- Mark Invoice as Sent ---
        logger.info(f"Marking invoice {ninja_invoice_id} as sent...")
        if not self.mark_invoice_sent(ninja_invoice_id):
            logger.warning("Failed to mark invoice as sent. Payment might remain unapplied initially.")
        else:
             logger.info(f"Invoice {ninja_invoice_id} marked as sent.")

        # --- Upload Custom Document (if provided) ---
        pdf_upload_success = False
        if custom_pdf_data:
            pdf_filename = f"{external_order_id}_invoice.pdf"
            logger.info(f"Attempting to upload custom PDF data as '{pdf_filename}' for Invoice ID: {ninja_invoice_id}...")
            pdf_upload_success = self.upload_invoice_document(ninja_invoice_id, custom_pdf_data, pdf_filename)
            if not pdf_upload_success:
                logger.warning("Failed to upload custom PDF document.")
            else:
                 logger.info("Custom PDF document uploaded successfully.")
        else:
             logger.info("No custom PDF data provided, skipping upload.")

        # --- Create Payment ---
        logger.info(f"Creating payment for Invoice ID: {ninja_invoice_id}, Amount: {payment_amount}, Date: {payment_date_str}")
        ninja_payment_id = self.create_payment(
            invoice_id=ninja_invoice_id,
            client_id=ninja_client_id,
            amount=payment_amount, # Use the provided price
            payment_date_str=payment_date_str,
            external_order_id=external_order_id,
            payment_type_id=target_payment_type_id
        )

        if not ninja_payment_id:
            logger.error("Failed to create payment record. Invoice exists but payment step failed.")
            return None
        else:
             logger.info(f"Payment created: ID={ninja_payment_id}")

        # --- Create Bank Transaction ---
        logger.info(f"Creating bank transaction for Invoice: {ninja_invoice_number}, Amount: {payment_amount}, Date: {payment_date_str}")
        ninja_bank_transaction_id = self.create_bank_transaction(
            processor_bank_account_id=target_processor_bank_id,
            bank_integration_id=target_bank_integration_id,
            amount=payment_amount, # Use the provided price
            date_str=payment_date_str,
            invoice_number=ninja_invoice_number,
            external_order_id=external_order_id
        )
        if not ninja_bank_transaction_id:
            logger.warning("Failed to create corresponding bank transaction record.")
        else:
             logger.info(f"Bank transaction created: ID={ninja_bank_transaction_id}")

        # --- Success ---
        logger.info("=" * 40)
        logger.info(f"Process Completed Successfully for {processor_type.upper()} Order: {external_order_id}")
        result = {
            "processor": processor_type,
            "client_id": ninja_client_id,
            "invoice_id": ninja_invoice_id,
            "invoice_number": ninja_invoice_number,
            "payment_id": ninja_payment_id,
            "bank_transaction_id": ninja_bank_transaction_id, # Could be None
            "pdf_upload_status": "Success" if pdf_upload_success else ("Skipped" if not custom_pdf_data else "Failed")
        }
        logger.info(f"Resulting IDs: {json.dumps(result, indent=2)}")
        logger.info("=" * 40)
        return result