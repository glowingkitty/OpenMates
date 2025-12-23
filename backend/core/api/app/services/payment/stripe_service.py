import stripe
import logging
from typing import Optional, Dict, Any, List
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

class StripeService:
    def __init__(self, secrets_manager: SecretsManager):
        self.secrets_manager = secrets_manager
        self._is_production = False
        self.api_key = None
        self.webhook_secret = None
        self.provider_name = "stripe" # Consistent with RevolutService

    async def initialize(self, is_production: bool):
        self._is_production = is_production
        self.api_key = await self._get_api_key()
        if not self.api_key:
            raise ValueError(f"Stripe API key for {'production' if is_production else 'sandbox'} environment is missing. Please add SECRET__STRIPE__{('PRODUCTION' if is_production else 'SANDBOX')}_SECRET_KEY to your Vault configuration.")
        
        self.webhook_secret = await self._get_webhook_secret()
        if not self.webhook_secret:
            raise ValueError(f"Stripe Webhook Secret for {'production' if is_production else 'sandbox'} environment is missing. Please add SECRET__STRIPE__{('PRODUCTION' if is_production else 'SANDBOX')}_WEBHOOK_SECRET to your Vault configuration.")
        
        stripe.api_key = self.api_key
        logger.info(f"StripeService initialized. Production: {self._is_production}")

    async def _get_api_key(self):
        key_suffix = "secret_key"
        if self._is_production:
            secret_key_name = f"production_{key_suffix}"
        else:
            secret_key_name = f"sandbox_{key_suffix}"
        
        secret_path = f"kv/data/providers/{self.provider_name}"
        api_key = await self.secrets_manager.get_secret(secret_path=secret_path, secret_key=secret_key_name)
        if not api_key:
            logger.error(f"Stripe Secret Key '{secret_key_name}' not found in '{secret_path}' using Secrets Manager.")
        return api_key

    async def _get_webhook_secret(self):
        key_suffix = "webhook_secret"
        if self._is_production:
            secret_key_name = f"production_{key_suffix}"
        else:
            secret_key_name = f"sandbox_{key_suffix}"

        secret_path = f"kv/data/providers/{self.provider_name}"
        secret = await self.secrets_manager.get_secret(secret_path=secret_path, secret_key=secret_key_name)
        if not secret:
            logger.error(f"Stripe Webhook Secret '{secret_key_name}' not found in '{secret_path}' using Secrets Manager.")
        return secret

    async def get_or_create_customer(self, email: str, existing_customer_id: Optional[str] = None) -> Optional[str]:
        """
        Get existing Stripe customer or create a new one.
        
        Args:
            email: Customer email address
            existing_customer_id: Optional existing Stripe customer ID to use
            
        Returns:
            Stripe customer ID, or None if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None
        
        # If we have an existing customer ID, verify it exists and return it
        if existing_customer_id:
            try:
                customer = stripe.Customer.retrieve(existing_customer_id)
                if customer and not getattr(customer, 'deleted', False):
                    logger.debug(f"Using existing Stripe customer: {existing_customer_id}")
                    return existing_customer_id
                else:
                    logger.warning(f"Existing customer {existing_customer_id} not found or deleted, creating new one")
            except stripe.error.StripeError as e:
                logger.warning(f"Error retrieving existing customer {existing_customer_id}: {e.user_message}, creating new one")
        
        # Create new customer
        try:
            customer = stripe.Customer.create(email=email)
            logger.info(f"Created new Stripe customer: {customer.id} for email: {email}")
            return customer.id
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating customer: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating Stripe customer: {str(e)}", exc_info=True)
            return None

    async def create_order(self, amount: int, currency: str, email: str, credits_amount: int, customer_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Creates a Stripe PaymentIntent using pre-created products.

        Args:
            amount: Amount in the smallest currency unit (e.g., cents).
            currency: 3-letter ISO currency code (e.g., "EUR").
            email: Customer's email address.
            credits_amount: Number of credits being purchased (for metadata).
            customer_id: Optional Stripe customer ID. If not provided, a customer will be created.

        Returns:
            A dictionary containing the PaymentIntent details, including 'id' and 'client_secret',
            or None if an error occurred.
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            # CRITICAL: Get or create Stripe customer BEFORE creating PaymentIntent
            # Stripe requires a customer when using setup_future_usage to save payment methods
            stripe_customer_id = await self.get_or_create_customer(email, customer_id)
            if not stripe_customer_id:
                logger.error("Failed to get or create Stripe customer for PaymentIntent")
                return None
            
            # First, try to find the product and price for this credit amount
            product_name = f"{credits_amount:,}".replace(",", ".") + " credits"
            price_id = await self._find_price_for_product(product_name, currency)
            
            if price_id:
                # Use the pre-created product/price
                logger.info(f"✅ Using pre-created Stripe product for {credits_amount} credits in {currency} (Price ID: {price_id})")
                return await self._create_payment_intent_with_price(price_id, email, credits_amount, stripe_customer_id)
            else:
                # Fallback to dynamic PaymentIntent if product not found
                logger.warning(f"⚠️ Pre-created product not found for {credits_amount} credits in {currency}, falling back to dynamic PaymentIntent")
                return await self._create_dynamic_payment_intent(amount, currency, email, credits_amount, stripe_customer_id)
                
        except Exception as e:
            logger.error(f"Unexpected error creating Stripe PaymentIntent: {str(e)}", exc_info=True)
            return None

    async def refund_payment(self, payment_intent_id: str, amount: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Refund a payment via Stripe.
        
        According to Stripe documentation, you can directly refund a PaymentIntent using
        the payment_intent parameter, which is simpler than retrieving the charge first.
        Supports both full and partial refunds.
        
        Args:
            payment_intent_id: The Stripe PaymentIntent ID (order_id)
            amount: Optional amount to refund in cents. If None, refunds the full amount.
            
        Returns:
            A dictionary containing refund details, or None if an error occurred.
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            import stripe as stripe_lib
            
            # Create refund directly using payment_intent parameter (recommended by Stripe docs)
            # This is simpler than retrieving the charge first
            refund_params = {
                "payment_intent": payment_intent_id
            }
            
            if amount is not None:
                refund_params["amount"] = amount
            
            refund = stripe_lib.Refund.create(**refund_params)
            
            logger.info(f"Successfully created refund {refund.id} for PaymentIntent {payment_intent_id}, amount: {refund.amount}")
            
            return {
                "refund_id": refund.id,
                "amount": refund.amount,
                "currency": refund.currency,
                "status": refund.status
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error processing refund for PaymentIntent {payment_intent_id}: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error processing Stripe refund for PaymentIntent {payment_intent_id}: {str(e)}", exc_info=True)
            return None

    async def _find_price_for_product(self, product_name: str, currency: str, recurring: bool = False) -> Optional[str]:
        """
        Find the price ID for a product by name and currency.
        
        Args:
            product_name: Name of the product to find
            currency: Currency code
            recurring: If True, only return recurring prices (for subscriptions).
                       If False, only return one-time prices (for PaymentIntents).
            
        Returns:
            Price ID if found, None otherwise
        """
        try:
            # Search for products by name
            products = stripe.Product.list(
                active=True,
                limit=100
            )
            
            for product in products.data:
                if product.name == product_name:
                    # Find the price for this currency
                    prices = stripe.Price.list(
                        product=product.id,
                        active=True
                    )
                    
                    for price in prices.data:
                        if price.currency == currency.lower():
                            # CRITICAL: Filter by price type based on recurring parameter
                            # Subscriptions require recurring prices, PaymentIntents require one-time prices
                            is_recurring = price.recurring is not None
                            
                            if recurring and is_recurring:
                                # Looking for recurring price and found one
                                logger.info(f"Found recurring price {price.id} for product '{product_name}' in {currency}")
                                return price.id
                            elif not recurring and not is_recurring:
                                # Looking for one-time price and found one
                                logger.info(f"Found one-time price {price.id} for product '{product_name}' in {currency}")
                                return price.id
                            # Otherwise, continue searching for the correct type
            
            price_type = "recurring" if recurring else "one-time"
            logger.warning(f"No {price_type} price found for product '{product_name}' in {currency}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding price for product '{product_name}': {str(e)}")
            return None

    async def _create_payment_intent_with_price(self, price_id: str, email: str, credits_amount: int, customer_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a PaymentIntent using a pre-created price.
        
        Args:
            price_id: Stripe price ID
            email: Customer email
            credits_amount: Number of credits
            customer_id: Stripe customer ID (REQUIRED for setup_future_usage)
            
        Returns:
            PaymentIntent details or None if error
        """
        try:
            # First, retrieve the price object to get amount and currency
            price = stripe.Price.retrieve(price_id)
            logger.info(f"Retrieved price {price_id}: {price.unit_amount} {price.currency}")
            
            # Create PaymentIntent with the price details
            # CRITICAL: Include customer parameter when using setup_future_usage
            # Stripe requires a customer to be associated with the PaymentIntent when saving
            # payment methods for future use. Without the customer, setup_future_usage won't work.
            payment_intent = stripe.PaymentIntent.create(
                amount=price.unit_amount,
                currency=price.currency,
                customer=customer_id,  # REQUIRED: Customer must be set for setup_future_usage to work
                receipt_email=email,
                metadata={
                    "credits_purchased": str(credits_amount),
                    "purchase_type": "credits",
                    "customer_email": email,
                    "price_id": price_id
                },
                automatic_payment_methods={"enabled": True},
                setup_future_usage="off_session",  # Optimize payment method for future subscriptions
            )
            
            logger.info(f"Stripe PaymentIntent created with product. ID: {payment_intent.id}, Customer: {customer_id}")
            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "status": payment_intent.status,
                "customer_id": customer_id,  # Return customer ID so it can be saved if it was newly created
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating PaymentIntent with product: {e.user_message}", exc_info=True)
            return None

    async def _create_dynamic_payment_intent(self, amount: int, currency: str, email: str, credits_amount: int, customer_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a dynamic PaymentIntent (fallback method).
        
        Args:
            amount: Amount in cents
            currency: Currency code
            email: Customer email
            credits_amount: Number of credits
            customer_id: Stripe customer ID (REQUIRED for setup_future_usage)
            
        Returns:
            PaymentIntent details or None if error
        """
        try:
            # CRITICAL: Include customer parameter when using setup_future_usage
            # Stripe requires a customer to be associated with the PaymentIntent when saving
            # payment methods for future use. Without the customer, setup_future_usage won't work.
            payment_intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                customer=customer_id,  # REQUIRED: Customer must be set for setup_future_usage to work
                receipt_email=email,
                metadata={
                    "credits_purchased": str(credits_amount),
                    "purchase_type": "credits",
                    "customer_email": email,
                },
                automatic_payment_methods={"enabled": True},
                setup_future_usage="off_session",  # Optimize payment method for future subscriptions
            )
            logger.info(f"Stripe dynamic PaymentIntent created successfully. ID: {payment_intent.id}, Customer: {customer_id}")
            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "status": payment_intent.status,
                "customer_id": customer_id,  # Return customer ID so it can be saved if it was newly created
            }
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating dynamic PaymentIntent: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating dynamic PaymentIntent: {str(e)}", exc_info=True)
            return None

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a Stripe PaymentIntent by its ID.

        Args:
            order_id: The ID of the PaymentIntent.

        Returns:
            A dictionary containing the PaymentIntent details, or None if not found or an error occurred.
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            payment_intent = stripe.PaymentIntent.retrieve(order_id)
            logger.info(f"Stripe PaymentIntent retrieved. ID: {payment_intent.id}, Status: {payment_intent.status}")

            charge_data = None
            if payment_intent.latest_charge:
                try:
                    charge = stripe.Charge.retrieve(payment_intent.latest_charge)
                    charge_data = charge
                    logger.info(f"Retrieved associated Stripe Charge: {charge.id}")
                except stripe.error.StripeError as e:
                    logger.warning(f"Failed to retrieve associated Stripe Charge {payment_intent.latest_charge}: {e.user_message}")
                except Exception as e:
                    logger.error(f"Unexpected error retrieving Stripe Charge {payment_intent.latest_charge}: {str(e)}", exc_info=True)

            cardholder_name = charge_data.billing_details.name if charge_data and hasattr(charge_data, 'billing_details') and charge_data.billing_details else None
            card_last_four = charge_data.payment_method_details.card.last4 if charge_data and hasattr(charge_data, 'payment_method_details') and hasattr(charge_data.payment_method_details, 'card') and charge_data.payment_method_details.card else None
            card_brand = charge_data.payment_method_details.card.brand if charge_data and hasattr(charge_data, 'payment_method_details') and hasattr(charge_data.payment_method_details, 'card') and charge_data.payment_method_details.card else None

            billing_address = {}
            if charge_data and hasattr(charge_data, 'billing_details') and charge_data.billing_details and hasattr(charge_data.billing_details, 'address') and charge_data.billing_details.address:
                address = charge_data.billing_details.address
                billing_address = {
                    "street_line_1": address.line1,
                    "street_line_2": address.line2,
                    "city": address.city,
                    "region": address.state,
                    "country_code": address.country,
                    "postcode": address.postal_code,
                }

            return {
                "id": payment_intent.id,
                "status": payment_intent.status,
                "client_secret": payment_intent.client_secret,
                "metadata": payment_intent.metadata,
                "amount": payment_intent.amount, # Add amount
                "currency": payment_intent.currency, # Add currency
                "payments": [ # Add a 'payments' list to mimic Revolut structure for compatibility
                    {
                        "state": payment_intent.status.upper(), # Use PaymentIntent status as payment state
                        "payment_method": {
                            "cardholder_name": cardholder_name,
                            "card_last_four": card_last_four,
                            "card_brand": card_brand,
                            "billing_address": billing_address
                        }
                    }
                ] if charge_data else [] # Ensure 'payments' is an empty list if no charges data
            }
        except stripe.error.InvalidRequestError as e:
            if "No such payment_intent" in str(e):
                logger.warning(f"Stripe PaymentIntent {order_id} not found.")
                return None
            logger.error(f"Stripe API error retrieving PaymentIntent {order_id}: {e.user_message}", exc_info=True)
            return None
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error retrieving PaymentIntent {order_id}: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving Stripe PaymentIntent {order_id}: {str(e)}", exc_info=True)
            return None

    async def verify_and_parse_webhook(self, payload: bytes, sig_header: str) -> Optional[Dict[str, Any]]:
        """
        Verifies the Stripe webhook signature and parses the event.

        Args:
            payload: The raw request body bytes.
            sig_header: The value of the 'Stripe-Signature' header.

        Returns:
            The parsed Stripe Event object as a dictionary, or None if verification fails.
        """
        if not self.webhook_secret:
            logger.error("Stripe Webhook Secret not initialized.")
            return None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            logger.info(f"Stripe webhook event verified successfully. Type: {event.type}")
            return event.to_dict()
        except ValueError as e:
            # Invalid payload
            logger.error(f"Stripe webhook ValueError: Invalid payload: {str(e)}")
            return None
        except stripe.error.SignatureVerificationError as e:
            # Invalid signature
            logger.error(f"Stripe webhook SignatureVerificationError: Invalid signature: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error verifying Stripe webhook: {str(e)}", exc_info=True)
            return None

    async def get_or_create_customer_for_payment_method(self, email: str, payment_method_id: str, existing_customer_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Gets or creates a Stripe customer for a payment method.
        Handles payment methods that are already attached to a customer (e.g., from PaymentIntent with setup_future_usage).
        
        Args:
            email: Customer email address
            payment_method_id: Stripe payment_method ID
            existing_customer_id: Optional existing Stripe customer ID to use if available
            
        Returns:
            Dictionary containing customer_id and payment_method_id, or None if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None
            
        try:
            # First, check if payment method is already attached to a customer
            payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
            
            if payment_method.customer:
                # Payment method is already attached to a customer
                existing_customer_id_from_pm = payment_method.customer
                logger.info(f"Payment method {payment_method_id} is already attached to customer {existing_customer_id_from_pm}")
                
                # Verify the customer exists and return it
                customer = stripe.Customer.retrieve(existing_customer_id_from_pm)
                # Check if customer is deleted - use getattr to safely check for deleted attribute
                # Deleted customers may not have the 'deleted' attribute, so we check if it exists and is True
                is_deleted = getattr(customer, 'deleted', False)
                if customer and not is_deleted:
                    # Set it as the default payment method if not already set
                    try:
                        stripe.Customer.modify(
                            customer.id,
                            invoice_settings={
                                "default_payment_method": payment_method_id
                            }
                        )
                        logger.info(f"Set payment method {payment_method_id} as default for existing customer {customer.id}")
                    except stripe.error.StripeError as e:
                        logger.warning(f"Failed to set default payment method for customer {customer.id}: {e.user_message}")
                    
                    return {
                        "customer_id": customer.id,
                        "payment_method_id": payment_method_id
                    }
                else:
                    logger.warning(f"Customer {existing_customer_id_from_pm} from payment method was deleted, creating new customer")
            
            # Payment method is not attached, or customer was deleted
            # Use existing customer ID if provided, otherwise create new customer
            if existing_customer_id:
                try:
                    customer = stripe.Customer.retrieve(existing_customer_id)
                    if customer and not customer.deleted:
                        logger.info(f"Using existing Stripe customer {existing_customer_id}")
                    else:
                        logger.warning(f"Existing customer {existing_customer_id} not found or deleted, creating new customer")
                        existing_customer_id = None
                except stripe.error.StripeError as e:
                    logger.warning(f"Error retrieving existing customer {existing_customer_id}: {e.user_message}, creating new customer")
                    existing_customer_id = None
            
            if not existing_customer_id:
                # Create new customer
                customer = stripe.Customer.create(email=email)
                logger.info(f"Created new Stripe customer {customer.id} for email: {email}")
            
            # Now try to attach the payment method to the customer
            try:
                stripe.PaymentMethod.attach(
                    payment_method_id,
                    customer=customer.id
                )
                
                # Set it as the default payment method
                stripe.Customer.modify(
                    customer.id,
                    invoice_settings={
                        "default_payment_method": payment_method_id
                    }
                )
                
                logger.info(f"Successfully attached payment method {payment_method_id} to customer {customer.id}")
                
            except stripe.error.StripeError as attach_error:
                # If attaching fails because it's already attached, that's okay - we already handled that case above
                error_msg = str(attach_error)
                if "already been attached" in error_msg.lower():
                    logger.info(f"Payment method {payment_method_id} is already attached to customer {customer.id} (this is expected)")
                    # This is fine - payment method is already attached
                elif "previously used" in error_msg.lower() or "may not be used again" in error_msg.lower():
                    logger.warning(
                        f"Payment method {payment_method_id} was previously used and cannot be attached to customer {customer.id}. "
                        f"This may prevent subscription creation. Error: {attach_error.user_message}"
                    )
                    # Return the customer anyway - the subscription creation will need to handle this
                else:
                    # Other errors - log and re-raise
                    logger.error(f"Error attaching payment method to customer: {attach_error.user_message}", exc_info=True)
                    raise
            
            return {
                "customer_id": customer.id,
                "payment_method_id": payment_method_id
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error getting/creating customer: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting/creating Stripe customer: {str(e)}", exc_info=True)
            return None

    async def create_customer(self, email: str, payment_method_id: str) -> Optional[Dict[str, Any]]:
        """
        Creates a Stripe customer and attaches a payment method.
        DEPRECATED: Use get_or_create_customer_for_payment_method instead.
        This method is kept for backward compatibility but may fail if payment method is already attached.
        
        Args:
            email: Customer email address
            payment_method_id: Stripe payment_method ID to attach
            
        Returns:
            Dictionary containing customer_id and payment_method_id, or None if error
        """
        # Delegate to the new method
        return await self.get_or_create_customer_for_payment_method(email, payment_method_id)
    
    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        metadata: Optional[Dict[str, str]] = None,
        default_payment_method: Optional[str] = None,
        billing_day_preference: str = 'anniversary'
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a monthly subscription for a customer.

        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID for the recurring charge
            metadata: Optional metadata to attach to the subscription
            default_payment_method: Optional payment method ID to use for the subscription.
                                   If not provided, Stripe will use the customer's default payment method.
            billing_day_preference: Billing day preference - 'anniversary' (default, 30 days from now) or 'first_of_month'

        Returns:
            Dictionary with subscription details or None if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            # CRITICAL: For monthly auto top-up subscriptions, we want to schedule the first charge based on billing preference.
            # The subscription should be created as 'active' but with the first billing cycle starting at the chosen date.
            # We use billing_cycle_anchor to set when the first invoice will be generated and charged.
            from datetime import datetime, timedelta, timezone
            import calendar

            # Calculate billing cycle anchor based on preference
            now = datetime.now(timezone.utc)

            if billing_day_preference == 'first_of_month':
                # Bill on the 1st of next month
                year = now.year
                month = now.month + 1
                if month > 12:
                    month = 1
                    year += 1
                billing_cycle_anchor = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
            else:
                # Anniversary billing: one month from now (default)
                billing_cycle_anchor = int((now + timedelta(days=30)).timestamp())
            
            subscription_params = {
                "customer": customer_id,
                "items": [{"price": price_id}],
                "metadata": metadata or {},
                "billing_cycle_anchor": billing_cycle_anchor,  # First charge in one month
                "proration_behavior": "none",  # Don't prorate the first period
                "expand": ["latest_invoice"]
            }
            
            # CRITICAL: If default_payment_method is provided, explicitly set it to ensure Stripe uses it
            # This is essential for subscriptions to work properly with saved payment methods
            if default_payment_method:
                subscription_params["default_payment_method"] = default_payment_method
                logger.debug(f"Using explicit payment method {default_payment_method} for subscription creation")
            
            subscription = stripe.Subscription.create(**subscription_params)
            
            logger.info(
                f"Stripe subscription created: {subscription.id} for customer: {customer_id}, "
                f"status: {subscription.status}, billing_cycle_anchor: {billing_cycle_anchor} "
                f"(first charge scheduled for one month from now)"
            )
            
            # CRITICAL: With billing_cycle_anchor set, Stripe creates the subscription as 'active' but doesn't
            # generate an invoice immediately. The first invoice will be generated at the billing_cycle_anchor date.
            # No client_secret is needed since no immediate payment is required.
            # The subscription will be active and ready, with the first charge scheduled for the billing_cycle_anchor date.
            
            # Get current_period_end - with billing_cycle_anchor, this should be set to the anchor date
            current_period_end = getattr(subscription, 'current_period_end', None)
            
            if current_period_end is None:
                # If current_period_end is not available, it should be the billing_cycle_anchor
                # But let's retrieve the subscription to be sure
                logger.debug(f"current_period_end not available on initial subscription object, retrieving full subscription details...")
                try:
                    full_subscription = stripe.Subscription.retrieve(subscription.id)
                    current_period_end = getattr(full_subscription, 'current_period_end', None)
                    if current_period_end:
                        logger.debug(f"Retrieved current_period_end from full subscription: {current_period_end}")
                    else:
                        # Fallback: use billing_cycle_anchor as current_period_end
                        current_period_end = billing_cycle_anchor
                        logger.debug(f"Using billing_cycle_anchor as current_period_end: {current_period_end}")
                except Exception as retrieve_error:
                    logger.warning(f"Failed to retrieve full subscription details: {retrieve_error}")
                    # Fallback: use billing_cycle_anchor
                    current_period_end = billing_cycle_anchor
            
            logger.info(
                f"Subscription {subscription.id} created successfully. Status: {subscription.status}, "
                f"first billing date: {datetime.fromtimestamp(current_period_end, tz=timezone.utc).isoformat()}"
            )
            
            return {
                "subscription_id": subscription.id,
                "status": subscription.status,  # Should be 'active' with billing_cycle_anchor
                "current_period_end": current_period_end,  # First billing date (one month from now)
                "cancel_at_period_end": getattr(subscription, 'cancel_at_period_end', False),
                "latest_invoice_id": subscription.latest_invoice if hasattr(subscription, 'latest_invoice') else None,
                "client_secret": None,  # No immediate payment required
                "payment_intent_id": None  # No payment intent needed
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating subscription: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating Stripe subscription: {str(e)}", exc_info=True)
            return None
    
    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a Stripe subscription by ID.
        
        Args:
            subscription_id: The Stripe subscription ID
            
        Returns:
            Dictionary with subscription details or None if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None
            
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            logger.info(f"Stripe subscription retrieved: {subscription.id}, status: {subscription.status}")
            
            # CRITICAL: Incomplete subscriptions don't have current_period_end, cancel_at_period_end, etc.
            # Use getattr with safe defaults to handle incomplete subscriptions gracefully
            current_period_end = getattr(subscription, 'current_period_end', None)
            cancel_at_period_end = getattr(subscription, 'cancel_at_period_end', False)
            canceled_at = getattr(subscription, 'canceled_at', None)
            metadata = getattr(subscription, 'metadata', {})
            
            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "current_period_end": current_period_end,  # None for incomplete subscriptions
                "cancel_at_period_end": cancel_at_period_end,
                "canceled_at": canceled_at,
                "metadata": metadata
            }
            
        except stripe.error.InvalidRequestError as e:
            if "No such subscription" in str(e):
                logger.warning(f"Stripe subscription {subscription_id} not found.")
                return None
            logger.error(f"Stripe API error retrieving subscription: {e.user_message}", exc_info=True)
            return None
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error retrieving subscription: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving Stripe subscription: {str(e)}", exc_info=True)
            return None
    
    async def cancel_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """
        Cancels a Stripe subscription immediately.
        For auto top-up subscriptions, cancellation is immediate rather than at period end.

        Args:
            subscription_id: The Stripe subscription ID to cancel

        Returns:
            Dictionary with cancellation details or None if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            # Cancel immediately for auto top-up subscriptions
            subscription = stripe.Subscription.cancel(subscription_id)

            logger.info(f"Stripe subscription {subscription_id} cancelled immediately")

            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "cancel_at_period_end": False,
                "canceled_at": subscription.canceled_at if hasattr(subscription, 'canceled_at') else None
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error canceling subscription: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error canceling Stripe subscription: {str(e)}", exc_info=True)
            return None
    
    async def get_payment_method(self, payment_intent_id: str) -> Optional[str]:
        """
        Retrieves the payment_method ID from a successful PaymentIntent.
        
        Args:
            payment_intent_id: The PaymentIntent ID
            
        Returns:
            Payment method ID or None if not found
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None
            
        try:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            if payment_intent.payment_method:
                logger.info(f"Retrieved payment_method {payment_intent.payment_method} from PaymentIntent {payment_intent_id}")
                return payment_intent.payment_method
            else:
                logger.warning(f"No payment_method found on PaymentIntent {payment_intent_id}")
                return None
                
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error retrieving payment method: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving payment method: {str(e)}", exc_info=True)
            return None

    async def list_payment_methods(self, customer_id: str) -> List[Dict[str, Any]]:
        """
        List all payment methods attached to a Stripe customer.
        
        Args:
            customer_id: The Stripe customer ID
            
        Returns:
            List of payment method dictionaries with card details, or empty list if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return []
            
        try:
            # List all payment methods for the customer
            payment_methods = stripe.PaymentMethod.list(
                customer=customer_id,
                type="card"
            )
            
            # Format payment methods for frontend
            formatted_methods = []
            for pm in payment_methods.data:
                card = pm.card if hasattr(pm, 'card') and pm.card else None
                if card:
                    formatted_methods.append({
                        "id": pm.id,
                        "type": pm.type,
                        "card": {
                            "brand": card.brand,
                            "last4": card.last4,
                            "exp_month": card.exp_month,
                            "exp_year": card.exp_year
                        },
                        "created": pm.created
                    })
            
            logger.info(f"Retrieved {len(formatted_methods)} payment methods for customer {customer_id}")
            return formatted_methods
                
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error listing payment methods: {e.user_message}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing payment methods: {str(e)}", exc_info=True)
            return []

    async def create_order_with_payment_method(
        self, 
        amount: int, 
        currency: str, 
        email: str, 
        credits_amount: int, 
        customer_id: str,
        payment_method_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a Stripe PaymentIntent using a saved payment method.
        
        Args:
            amount: Amount in the smallest currency unit (e.g., cents).
            currency: 3-letter ISO currency code (e.g., "EUR").
            email: Customer's email address.
            credits_amount: Number of credits being purchased (for metadata).
            customer_id: Stripe customer ID (required).
            payment_method_id: The saved payment method ID to use.
            
        Returns:
            A dictionary containing the PaymentIntent details, including 'id' and 'client_secret',
            or None if an error occurred.
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            # Verify payment method belongs to customer
            try:
                payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                if payment_method.customer != customer_id:
                    logger.error(f"Payment method {payment_method_id} does not belong to customer {customer_id}")
                    return None
            except stripe.error.StripeError as e:
                logger.error(f"Error retrieving payment method {payment_method_id}: {e.user_message}")
                return None
            
            # Try to find the product and price for this credit amount
            product_name = f"{credits_amount:,}".replace(",", ".") + " credits"
            price_id = await self._find_price_for_product(product_name, currency)
            
            if price_id:
                # Use the pre-created product/price
                logger.info(f"✅ Using pre-created Stripe product for {credits_amount} credits in {currency} (Price ID: {price_id})")
                return await self._create_payment_intent_with_saved_method(
                    price_id, email, credits_amount, customer_id, payment_method_id
                )
            else:
                # Fallback to dynamic PaymentIntent if product not found
                logger.warning(f"⚠️ Pre-created product not found for {credits_amount} credits in {currency}, falling back to dynamic PaymentIntent")
                return await self._create_dynamic_payment_intent_with_method(
                    amount, currency, email, credits_amount, customer_id, payment_method_id
                )
                
        except Exception as e:
            logger.error(f"Unexpected error creating PaymentIntent with saved method: {str(e)}", exc_info=True)
            return None

    async def _create_payment_intent_with_saved_method(
        self, 
        price_id: str, 
        email: str, 
        credits_amount: int, 
        customer_id: str,
        payment_method_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Create a PaymentIntent using a pre-created price and saved payment method.
        """
        try:
            payment_intent = stripe.PaymentIntent.create(
                amount=None,  # Amount comes from price
                currency=None,  # Currency comes from price
                customer=customer_id,
                payment_method=payment_method_id,
                payment_method_types=["card"],
                confirmation_method="manual",
                confirm=False,  # Don't confirm immediately - let frontend handle confirmation
                return_url=None,  # No redirect needed
                metadata={
                    "credits_amount": str(credits_amount),
                    "email": email,
                    "order_type": "credit_purchase"
                },
                automatic_payment_methods={"enabled": False},  # Disable automatic payment methods when using saved method
                payment_method_options={
                    "card": {
                        "capture_method": "automatic"
                    }
                }
            )
            
            # Attach the price to the PaymentIntent
            # Note: Stripe doesn't directly support attaching prices to PaymentIntents
            # We need to set the amount from the price
            price = stripe.Price.retrieve(price_id)
            payment_intent = stripe.PaymentIntent.modify(
                payment_intent.id,
                amount=price.unit_amount,
                currency=price.currency
            )
            
            logger.info(f"Created PaymentIntent {payment_intent.id} with saved payment method {payment_method_id} for {credits_amount} credits")
            
            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "status": payment_intent.status
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating PaymentIntent with saved method: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating PaymentIntent with saved method: {str(e)}", exc_info=True)
            return None

    async def _create_dynamic_payment_intent_with_method(
        self,
        amount: int,
        currency: str,
        email: str,
        credits_amount: int,
        customer_id: str,
        payment_method_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Create a PaymentIntent dynamically with a saved payment method (fallback when product not found).
        """
        try:
            payment_intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency.lower(),
                customer=customer_id,
                payment_method=payment_method_id,
                payment_method_types=["card"],
                confirmation_method="manual",
                confirm=False,  # Don't confirm immediately - let frontend handle confirmation
                return_url=None,
                metadata={
                    "credits_amount": str(credits_amount),
                    "email": email,
                    "order_type": "credit_purchase"
                },
                automatic_payment_methods={"enabled": False},  # Disable automatic payment methods when using saved method
                payment_method_options={
                    "card": {
                        "capture_method": "automatic"
                    }
                }
            )
            
            logger.info(f"Created dynamic PaymentIntent {payment_intent.id} with saved payment method {payment_method_id} for {credits_amount} credits")
            
            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "status": payment_intent.status
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating dynamic PaymentIntent with saved method: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating dynamic PaymentIntent with saved method: {str(e)}", exc_info=True)
            return None

    async def create_support_order(self, amount: int, currency: str, email: str, is_recurring: bool, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Creates a Stripe PaymentIntent or Subscription for supporter contributions.

        Args:
            amount: Amount in the smallest currency unit (e.g., cents).
            currency: 3-letter ISO currency code (e.g., "EUR").
            email: Customer's email address.
            is_recurring: True for monthly subscriptions, False for one-time payments.
            user_id: Optional authenticated user ID.

        Returns:
            A dictionary containing payment details and customer portal link for recurring payments,
            or None if an error occurred.
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            # Get or create Stripe customer
            stripe_customer_id = await self.get_or_create_customer(email)
            if not stripe_customer_id:
                logger.error("Failed to get or create Stripe customer for support order")
                return None

            # Find the appropriate supporter product
            if is_recurring:
                product_name = "Monthly Supporter Contribution"
            else:
                product_name = "Supporter Contribution"

            price_id = await self._find_price_for_product(product_name, currency, is_recurring)

            if not price_id:
                logger.error(f"No supporter product found for {amount} {currency} (recurring: {is_recurring})")
                return None

            logger.info(f"✅ Using supporter product for {amount} {currency} (recurring: {is_recurring}, Price ID: {price_id})")

            if is_recurring:
                return await self._create_supporter_subscription(price_id, email, stripe_customer_id, amount, currency, user_id)
            else:
                return await self._create_supporter_payment_intent(price_id, email, stripe_customer_id, amount, currency, user_id)

        except Exception as e:
            logger.error(f"Unexpected error creating supporter order: {str(e)}", exc_info=True)
            return None

    async def _create_supporter_payment_intent(self, price_id: str, email: str, customer_id: str, amount: int, currency: str, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Create a one-time PaymentIntent for supporter contribution.
        """
        try:
            metadata = {
                "product_type": "supporter_contribution",
                "is_recurring": "false",
                "email": email
            }

            if user_id:
                metadata["user_id"] = user_id

            payment_intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency.lower(),
                customer=customer_id,
                metadata=metadata,
                automatic_payment_methods={"enabled": True},
                setup_future_usage=None,  # Don't save payment method for supporters
                description="One-time supporter contribution to OpenMates development"
            )

            logger.info(f"Created supporter PaymentIntent {payment_intent.id} for {amount/100:.2f}")

            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "status": payment_intent.status,
                "order_id": payment_intent.id
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating supporter PaymentIntent: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating supporter PaymentIntent: {str(e)}", exc_info=True)
            return None

    async def _create_supporter_subscription(self, price_id: str, email: str, customer_id: str, amount: int, currency: str, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Create a recurring subscription for supporter contribution.
        """
        try:
            metadata = {
                "product_type": "supporter_contribution",
                "is_recurring": "true",
                "email": email
            }

            if user_id:
                metadata["user_id"] = user_id

            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata=metadata,
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"],
                description="Monthly supporter contribution to OpenMates development"
            )

            # Create customer portal link for subscription management
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url="https://openmates.org"  # Configure this URL as needed
            )

            logger.info(f"Created supporter subscription {subscription.id} for {amount/100:.2f} {currency.upper()}/month")
            logger.info(f"Created customer portal link: {portal_session.url}")

            response_data = {
                "id": subscription.id,
                "status": subscription.status,
                "order_id": subscription.id,
                "customer_portal_url": portal_session.url
            }

            # Include payment intent details if available
            if hasattr(subscription, 'latest_invoice') and subscription.latest_invoice:
                if hasattr(subscription.latest_invoice, 'payment_intent') and subscription.latest_invoice.payment_intent:
                    payment_intent = subscription.latest_invoice.payment_intent
                    response_data["client_secret"] = payment_intent.client_secret
                    response_data["payment_intent_id"] = payment_intent.id

            return response_data

        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating supporter subscription: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating supporter subscription: {str(e)}", exc_info=True)
            return None

    async def close(self):
        logger.info("StripeService close called.")
        pass
