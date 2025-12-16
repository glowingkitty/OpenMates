# backend/core/api/app/services/invoiceninja/invoiceninja.py
import requests
import json
import logging
import os # Added for environment variable check
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from datetime import date # Added for payment date

# Assuming SecretsManager is accessible via this relative path
# Adjust the import path if necessary based on your project structure
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Import the functions from submodules
from backend.core.api.app.services.invoiceninja import clients, invoices, payments, bank_accounts, transactions, countries

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
        self.INVOICE_NINJA_URL = await self.secrets_manager.get_secret(secret_path="kv/data/providers/invoice_ninja", secret_key="url")
        
        is_dev = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"
        if is_dev:
            self.API_TOKEN = await self.secrets_manager.get_secret(secret_path="kv/data/providers/invoice_ninja", secret_key="sandbox_api_key")
            logger.info("Using Invoice Ninja SANDBOX API Key.")
        else:
            self.API_TOKEN = await self.secrets_manager.get_secret(secret_path="kv/data/providers/invoice_ninja", secret_key="production_api_key")
            logger.info("Using Invoice Ninja PRODUCTION API Key.")

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
        data = None
        upload_headers = None
        try:
            # Use multipart/form-data for file uploads from bytes
            # API docs suggest 'documents[0]' as the key for the file part
            # and '_method': 'PUT' as a separate form field.
            files = {'documents[0]': (filename, file_data, 'application/pdf')}
            data = {'_method': 'PUT'} # Send _method=PUT in the data payload

            # Create headers for upload, removing Content-Type for requests lib to set it
            upload_headers = self.headers.copy()
            if 'Content-Type' in upload_headers:
                del upload_headers['Content-Type'] # requests sets multipart/form-data header automatically

            # --- Added Logging ---
            logger.info(f"Attempting file upload to URL: {url}")
            logger.debug(f"Upload Headers: {json.dumps(upload_headers)}")
            # Note: Logging 'files' directly can be verbose/problematic if file_data is large.
            # Log file metadata instead.
            logger.debug(f"Upload Files key: 'documents[0]', filename: '{filename}', content_type: 'application/pdf'")
            logger.debug(f"Upload Data: {json.dumps(data)}")
            # --- End Added Logging ---

            # Use POST, include _method=PUT in the data payload, and provide files
            response = requests.post(url, headers=upload_headers, files=files, data=data, timeout=30) # Longer timeout for uploads
            logger.info(f"Upload request completed with status code: {response.status_code}")
            response.raise_for_status()
            # Assuming success if no exception is raised
            logger.info(f"Successfully uploaded document '{filename}' to {url}")
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
                    logger.error(f"Error closing file handle: {e_close}")


    # --- Client Operations ---
    def find_client_by_hash(self, user_hash: str) -> Optional[str]:
        return clients.find_client_by_hash(self, user_hash)

    def create_client(self, user_hash: str, external_order_id: str, client_details: Dict[str, Any]) -> Optional[str]:
        return clients.create_client(self, user_hash, external_order_id, client_details)

    # --- Invoice Operations ---
    def create_invoice(self, 
                       client_id: str, 
                       invoice_items: List[Dict[str, Any]],
                       invoice_date: str,
                       due_date: str,
                       payment_processor: str,
                       external_order_id: str,
                       custom_invoice_number: str,
                       mark_sent: bool
                       ) -> Tuple[Optional[str], Optional[str]]:
        return invoices.create_invoice(self,
                                       client_id = client_id, 
                                       invoice_items = invoice_items,
                                       invoice_date = invoice_date,
                                       due_date = due_date,
                                       payment_processor = payment_processor,
                                       external_order_id = external_order_id,
                                       custom_invoice_number = custom_invoice_number,
                                       mark_sent = mark_sent
                                       )

    # Removed mark_invoice_sent method definition as it's no longer needed.

    def upload_invoice_document(self, invoice_id: str, pdf_data: bytes, filename: str) -> bool:
        # Uses the dedicated _make_file_upload_request method
        # Assuming invoices.upload_invoice_document is updated to accept bytes and filename
        return invoices.upload_invoice_document(self, invoice_id, pdf_data, filename)

    def upload_credit_document(self, credit_id: str, pdf_data: bytes, filename: str) -> bool:
        """
        Uploads a custom PDF document to an existing credit note.
        
        Args:
            credit_id: The ID of the credit note to upload the document to.
            pdf_data: The PDF file content as bytes.
            filename: The desired filename for the uploaded document.
            
        Returns:
            True if successful, False otherwise.
        """
        logger.info(f"Attempting to upload document '{filename}' (from bytes) to credit note ID {credit_id}...")
        
        endpoint = f'/credits/{credit_id}/upload'
        
        # Use the same file upload mechanism as invoices
        success = self._make_file_upload_request(endpoint, pdf_data, filename)
        
        if success:
            logger.info(f"Successfully uploaded document to credit note ID {credit_id}.")
        else:
            logger.error(f"Failed to upload document to credit note ID {credit_id}.")
        
        return success

    # --- Payment Operations ---
    # Corrected signature to match payments.create_payment structure
    def create_payment(self,
                       client_id: str,
                       amount: float,
                       payment_date_str: str,
                       invoice_id: str,
                       external_order_id: Optional[str] = None, # Mapped to transaction_reference
                       payment_type: Optional[str] = None
                       ) -> Optional[str]:
        # Call the actual implementation with correctly mapped arguments
        return payments.create_payment(
            service_instance=self,
            client_id=client_id,
            amount=amount,
            date=payment_date_str,
            invoice_id=invoice_id,
            payment_type=payment_type,
            transaction_reference=external_order_id
        )

    # --- Bank Account Operations ---
    def create_bank_transaction(self, processor_bank_account_id: str, bank_integration_id: str, amount: float, date_str: str, invoice_number: str, external_order_id: str, base_type: str, currency_code: str) -> Optional[str]:
        """
        Creates a bank transaction in Invoice Ninja.

        Args:
            processor_bank_account_id: The HASHED ID of the bank account (e.g., self._revolut_bank_account_id).
            bank_integration_id: The HASHED ID of the bank integration (e.g., self._revolut_bank_integration_id).
            amount: Transaction amount.
            date_str: Transaction date (YYYY-MM-DD).
            invoice_number: Associated Invoice Ninja invoice number.
            external_order_id: Your internal order ID.
            base_type: CREDIT or DEBIT
            currency_id: id of currency

        Returns:
            The HASHED ID of the created bank transaction, or None on failure.
        """
        return transactions.create_bank_transaction(self,
                                                    processor_bank_account_id = processor_bank_account_id,
                                                    bank_integration_id = bank_integration_id,
                                                    amount = amount,
                                                    date_str = date_str,
                                                    invoice_number = invoice_number,
                                                    external_order_id = external_order_id,
                                                    base_type = base_type,
                                                    currency_code = currency_code
                                                    )

    def match_bank_transaction_to_payment(self, transaction_id: str, payment_id: str) -> bool:
        """Matches a bank transaction to a payment."""
        # Calls the updated function from the transactions module now
        return transactions.match_transaction_to_payment(self, transaction_id, payment_id)

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
        customer_account_id: str,  # Changed from customer_email to customer_account_id
        customer_country_code: str,
        credits_value: int,
        purchase_price_value: float, # Direct price input
        currency_code: str,
        card_brand_lower: str, # visa, mastercard, american_express
        invoice_date: str, # Added
        due_date: str, # Added
        payment_processor: str, # Added (replaces processor_type)
        custom_invoice_number: str, # Added
        custom_pdf_data: Optional[bytes] = None, # PDF data as bytes
        is_gift_card: bool = False  # Flag to indicate if this is a gift card purchase
        ):
        """
        Handles the full workflow for processing an income transaction,
        using a directly provided purchase price and invoice details.
        """
        # Rename payment_processor to processor_type for internal consistency
        processor_type = payment_processor

        logger.info("=" * 40)
        logger.info(f"Starting Process for {processor_type.upper()} Order: {external_order_id} (User Hash: {user_hash})")

        # --- Use provided dates ---
        # payment_date_str is used for payment and bank transaction, derived from invoice_date
        payment_date_str = invoice_date
        logger.info(f"Using invoice date: {invoice_date}, due date: {due_date}, payment date: {payment_date_str}")

        # --- Use provided price directly ---
        payment_amount = purchase_price_value
        logger.info(f"Using provided purchase price: {payment_amount}")

        # --- Determine Processor Specific IDs using fetched values ---
        target_processor_bank_id: Optional[str] = None
        target_bank_integration_id: Optional[str] = None

        if processor_type.lower() == 'revolut':
            target_processor_bank_id = self._revolut_bank_account_id
            target_bank_integration_id = self._revolut_bank_integration_id
        elif processor_type.lower() == 'stripe':
            target_processor_bank_id = self._stripe_bank_account_id
            target_bank_integration_id = self._stripe_bank_integration_id
        else:
            logger.warning(f"Unknown processor type '{processor_type}'. Cannot determine bank/integration IDs.")
            # Decide if you should abort or continue without bank details

        # --- Sanity Check Fetched IDs ---
        if target_processor_bank_id is None:
            logger.error(f"Bank Account ID for the processor type '{processor_type}' was not found or assigned during initialization. Aborting.")
            return None
        if target_bank_integration_id is None:
            logger.error(f"Bank Integration ID for the processor type '{processor_type}' was not found or assigned during initialization. Aborting.")
            return None

        # --- Find or Create Client ---
        ninja_client_id = self.find_client_by_hash(user_hash)
        country_id = countries.get_country_id(customer_country_code) # Use imported function
        if not ninja_client_id:
            client_details = {
                "first_name": f"Account ID: {customer_account_id}",  # Put account ID in first_name field
                "last_name": "",  # Leave last_name empty
                "email": "",  # Leave email field empty
                "country_id": country_id,
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
        
        # For gift cards, prefix the product name with "Gift card - "
        if is_gift_card:
            product_key = f"Gift card - {product_key}"
            logger.info(f"Gift card purchase detected, product key prefixed: {product_key}")
        
        logger.info(f"Selected product key for invoice line item (based on credits {credits_value}): {product_key}")

        # Prepare invoice items (using determined product key and provided price)
        invoice_item_data = [
            {
                "product_key": product_key,
                "quantity": 1,
                "cost": purchase_price_value, # Use the provided price for the line item cost,
                "line_total": purchase_price_value,
                "tax_id": 3 # The tax ID of the product: 1 product, 2 service, 3 digital, 4 shipping, 5 exempt, 5 reduced tax, 7 override, 8 zero rate, 9 reverse tax
            }
        ]

        # --- Create Invoice ---
        logger.info(f"Creating invoice for Client ID: {ninja_client_id} with items: {invoice_item_data}")
        ninja_invoice_id, ninja_invoice_number = self.create_invoice(
            client_id = ninja_client_id,
            invoice_items = invoice_item_data,
            invoice_date = invoice_date, # Use passed invoice_date
            due_date = due_date, # Use passed due_date
            payment_processor = processor_type, # Use passed processor_type
            external_order_id = external_order_id,
            custom_invoice_number = custom_invoice_number, # Use passed custom_invoice_number
            mark_sent = True # Explicitly mark as sent on creation
            )

        # Note: The returned ninja_invoice_number from create_invoice might differ
        # from the custom_invoice_number if Invoice Ninja enforces its own numbering.
        # We will use the *returned* ninja_invoice_number for subsequent steps.
        if not ninja_invoice_id or not ninja_invoice_number:
            logger.error("Failed to create invoice. Aborting.")
            return None
        else:
             logger.info(f"Invoice created: ID={ninja_invoice_id}, Number={ninja_invoice_number}")

        # --- Create Payment Explicitly ---
        # Invoice is marked as sent during creation via query parameter.
        logger.info(f"Creating payment for Invoice ID: {ninja_invoice_id}, Amount: {payment_amount}, Date: {payment_date_str}")
        # Call the corrected self.create_payment wrapper using keyword arguments
        payment_types = {
            "visa": "Visa Card",
            "mastercard": "MasterCard",
            "american_express": "American Express"
        }
        payment_type_default = "Debit"
        payment_type = payment_types[card_brand_lower] if card_brand_lower in payment_types else payment_type_default
        
        ninja_payment_id = self.create_payment(
            client_id=ninja_client_id,
            amount=payment_amount,
            payment_date_str=payment_date_str,
            invoice_id=ninja_invoice_id,
            external_order_id=external_order_id, # Passed to wrapper, maps to transaction_reference
            payment_type=payment_type
        )
        if not ninja_payment_id:
            logger.error(f"Failed to create payment for invoice {ninja_invoice_id}. The invoice might not be marked as paid automatically.")
            # Decide if this is critical enough to abort or just warn
        else:
            logger.info(f"Payment created successfully: ID={ninja_payment_id}")
            # Invoice Ninja should automatically update the invoice status to 'paid' now.


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


        # --- Create Bank Transaction ---
        # Payment is now created explicitly above.
        # We still need the bank transaction for reconciliation.
        logger.info(f"Creating bank transaction for Invoice: {ninja_invoice_number}, Amount: {payment_amount}, Date: {payment_date_str}")
        ninja_bank_transaction_id = self.create_bank_transaction(
            processor_bank_account_id=target_processor_bank_id,
            bank_integration_id=target_bank_integration_id,
            amount=payment_amount, # Use the provided price
            date_str=payment_date_str,
            invoice_number=ninja_invoice_number,
            external_order_id=external_order_id,
            base_type="CREDIT", # CREDIT -> we get money, DEBIT -> we pay money
            currency_code=currency_code
        )
        transaction_match_success = False
        if not ninja_bank_transaction_id:
            logger.warning("Failed to create corresponding bank transaction record. Cannot match.")
        else:
             logger.info(f"Bank transaction created: ID={ninja_bank_transaction_id}")
             # --- Match Bank Transaction to Payment ---
             logger.info(f"Attempting to match bank transaction {ninja_bank_transaction_id} to payment {ninja_payment_id}...")
             transaction_match_success = self.match_bank_transaction_to_payment(
                 transaction_id=ninja_bank_transaction_id,
                 payment_id=ninja_payment_id # Use payment_id now
             )
             if transaction_match_success:
                 logger.info("Successfully matched bank transaction to payment.")
             else:
                 logger.warning("Failed to match bank transaction to payment.")


        # --- Success ---
        logger.info(f"Process Completed for {processor_type.upper()} Order: {external_order_id}")

    def create_credit_note(
        self,
        client_id: str,
        invoice_id: str,
        credit_amount: float,
        currency_code: str,
        credit_date: str,
        credit_number: str,
        payment_processor: str,
        external_order_id: str,
        referenced_invoice_number: Optional[str] = None
    ) -> Optional[str]:
        """
        Creates a credit note in Invoice Ninja for a refund.
        
        Args:
            client_id: Invoice Ninja client ID
            invoice_id: Invoice Ninja invoice ID that this credit note references
            credit_amount: Amount of the credit note (positive value, will be negated)
            currency_code: Currency code (e.g., 'eur', 'usd')
            credit_date: Date of the credit note (ISO format: YYYY-MM-DD)
            credit_number: Credit note number (e.g., 'CN-MRRUNHO-1')
            payment_processor: Payment processor name (e.g., 'stripe', 'revolut')
            external_order_id: External order ID from payment provider
            referenced_invoice_number: Original invoice number for reference
            
        Returns:
            Credit note ID if successful, None otherwise
        """
        try:
            # Prepare credit note data
            # Invoice Ninja expects credits to be negative amounts
            # Note: Invoice Ninja uses currency_id as a numeric ID, but we'll try with currency code first
            # If that doesn't work, we may need to look up the currency ID
            credit_data = {
                "client_id": client_id,
                "number": credit_number,
                "date": credit_date,
                "amount": -abs(credit_amount),  # Negative amount for credit
                "currency_id": currency_code.upper(),  # Try currency code (e.g., "EUR", "USD")
                "status_id": "2",  # Status ID 2 = "Sent" (active credit note)
                "custom_value1": payment_processor,  # Store payment processor
                "custom_value2": external_order_id,  # Store external order ID
                "private_notes": f"Credit note for refund. Referenced invoice: {referenced_invoice_number or 'N/A'}"
            }
            
            # Create credit note via API
            logger.info(f"Creating credit note in Invoice Ninja: {credit_number}, Amount: {credit_amount} {currency_code}")
            response = self.make_api_request('POST', '/credits', data=credit_data)
            
            if response and 'data' in response:
                credit_id = response['data'].get('id')
                if credit_id:
                    logger.info(f"Credit note created successfully in Invoice Ninja: ID={credit_id}")
                    return credit_id
                else:
                    logger.error("Credit note creation response missing ID")
            else:
                logger.error(f"Failed to create credit note. Response: {response}")
                
        except Exception as e:
            logger.error(f"Exception creating credit note in Invoice Ninja: {str(e)}", exc_info=True)
        
        return None

    def process_refund_transaction(
        self,
        user_hash: str,
        external_order_id: str,
        invoice_id: str,
        customer_firstname: str,
        customer_lastname: str,
        customer_account_id: str,
        customer_country_code: str,
        refund_amount_value: float,
        currency_code: str,
        refund_date: str,
        payment_processor: str,
        custom_credit_note_number: str,
        custom_pdf_data: Optional[bytes] = None,
        referenced_invoice_number: str = None
    ):
        """
        Handles the full workflow for processing a refund transaction.
        Uploads credit note PDF to the original invoice in Invoice Ninja.
        """
        processor_type = payment_processor

        logger.info("=" * 40)
        logger.info(f"Starting Refund Process for {processor_type.upper()} Order: {external_order_id} (User Hash: {user_hash})")

        # Find the original invoice in Invoice Ninja by external_order_id
        # We need to search for the invoice that matches this order_id
        logger.info(f"Searching for invoice with external_order_id: {external_order_id}")
        
        # Find or Create Client (same as income transaction)
        ninja_client_id = self.find_client_by_hash(user_hash)
        country_id = countries.get_country_id(customer_country_code)
        if not ninja_client_id:
            client_details = {
                "first_name": f"Account ID: {customer_account_id}",
                "last_name": "",
                "email": "",
                "country_id": country_id,
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

        # Search for the invoice by external_order_id (stored in custom_value2)
        # Invoice Ninja API: GET /invoices?client_id={client_id}&custom_value2={external_order_id}
        search_params = {
            "client_id": ninja_client_id,
            "custom_value2": external_order_id
        }
        
        invoice_search_result = self.make_api_request('GET', '/invoices', params=search_params)
        
        ninja_invoice_id = None
        if invoice_search_result and 'data' in invoice_search_result:
            invoices = invoice_search_result['data']
            if invoices and len(invoices) > 0:
                # Get the first matching invoice (should be unique by order_id)
                ninja_invoice_id = invoices[0].get('id')
                logger.info(f"Found invoice in Invoice Ninja: ID={ninja_invoice_id}")
            else:
                logger.warning(f"No invoice found in Invoice Ninja for order_id: {external_order_id}")
        else:
            logger.warning(f"Failed to search for invoice in Invoice Ninja for order_id: {external_order_id}")

        # Create credit note in Invoice Ninja if we found the invoice
        ninja_credit_id = None
        if ninja_invoice_id:
            logger.info(f"Creating credit note in Invoice Ninja for invoice ID: {ninja_invoice_id}")
            ninja_credit_id = self.create_credit_note(
                client_id=ninja_client_id,
                invoice_id=ninja_invoice_id,
                credit_amount=refund_amount_value,
                currency_code=currency_code,
                credit_date=refund_date,
                credit_number=custom_credit_note_number,
                payment_processor=payment_processor,
                external_order_id=external_order_id,
                referenced_invoice_number=referenced_invoice_number
            )
            if not ninja_credit_id:
                logger.warning("Failed to create credit note in Invoice Ninja.")
            else:
                logger.info(f"Credit note created successfully in Invoice Ninja: ID={ninja_credit_id}")
        else:
            logger.warning(f"Cannot create credit note: Invoice not found in Invoice Ninja for order_id: {external_order_id}")

        # Upload the credit note PDF to the credit note (not the invoice)
        if ninja_credit_id and custom_pdf_data:
            pdf_filename = f"{external_order_id}_credit_note_{custom_credit_note_number}.pdf"
            logger.info(f"Attempting to upload credit note PDF '{pdf_filename}' to Credit Note ID: {ninja_credit_id}...")
            pdf_upload_success = self.upload_credit_document(ninja_credit_id, custom_pdf_data, pdf_filename)
            if not pdf_upload_success:
                logger.warning("Failed to upload credit note PDF document to Invoice Ninja.")
            else:
                logger.info("Credit note PDF document uploaded successfully to Invoice Ninja.")
        else:
            if not ninja_credit_id:
                logger.warning(f"Cannot upload credit note PDF: Credit note not created in Invoice Ninja for order_id: {external_order_id}")
            if not custom_pdf_data:
                logger.info("No credit note PDF data provided, skipping upload to Invoice Ninja.")

        # Create a bank transaction for the refund (DEBIT - we pay money back)
        # Determine Processor Specific IDs
        target_processor_bank_id: Optional[str] = None
        target_bank_integration_id: Optional[str] = None

        if processor_type.lower() == 'revolut':
            target_processor_bank_id = self._revolut_bank_account_id
            target_bank_integration_id = self._revolut_bank_integration_id
        elif processor_type.lower() == 'stripe':
            target_processor_bank_id = self._stripe_bank_account_id
            target_bank_integration_id = self._stripe_bank_integration_id
        else:
            logger.warning(f"Unknown processor type '{processor_type}'. Cannot determine bank/integration IDs.")

        # Create bank transaction for refund (DEBIT)
        if target_processor_bank_id and target_bank_integration_id:
            # Use the referenced invoice number if available, otherwise use credit note number
            invoice_number_for_transaction = referenced_invoice_number if referenced_invoice_number else custom_credit_note_number
            
            logger.info(f"Creating bank transaction for refund: Amount: {refund_amount_value}, Date: {refund_date}")
            ninja_bank_transaction_id = self.create_bank_transaction(
                processor_bank_account_id=target_processor_bank_id,
                bank_integration_id=target_bank_integration_id,
                amount=refund_amount_value,
                date_str=refund_date,
                invoice_number=invoice_number_for_transaction,
                external_order_id=external_order_id,
                base_type="DEBIT",  # DEBIT -> we pay money back
                currency_code=currency_code
            )
            if not ninja_bank_transaction_id:
                logger.warning("Failed to create bank transaction record for refund.")
            else:
                logger.info(f"Bank transaction created for refund: ID={ninja_bank_transaction_id}")
        else:
            logger.warning(f"Cannot create bank transaction: Bank account/integration IDs not found for processor '{processor_type}'")

        # --- Success ---
        logger.info(f"Refund Process Completed for {processor_type.upper()} Order: {external_order_id}")

    async def close(self):
        """
        Performs any necessary cleanup for the Invoice Ninja service.
        Currently, there are no explicit client connections to close for requests.
        """
        logger.info("Closing Invoice Ninja service (no explicit client connections to close).")
