import stripe
import logging
from typing import Optional, Dict, Any
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
                if customer and not customer.deleted:
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
        metadata: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a monthly subscription for a customer.
        
        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID for the recurring charge
            metadata: Optional metadata to attach to the subscription
            
        Returns:
            Dictionary with subscription details or None if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None
            
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata=metadata or {},
                payment_behavior='default_incomplete',
                expand=['latest_invoice.payment_intent']
            )
            
            logger.info(f"Stripe subscription created: {subscription.id} for customer: {customer_id}")
            
            # CRITICAL: When using payment_behavior='default_incomplete', some fields may not be immediately available
            # Use getattr with safe defaults to handle incomplete subscriptions
            # If current_period_end is missing, retrieve the subscription again to get full details
            current_period_end = getattr(subscription, 'current_period_end', None)
            
            if current_period_end is None:
                # Subscription might be incomplete - retrieve it again to get full details
                logger.debug(f"current_period_end not available on initial subscription object, retrieving full subscription details...")
                try:
                    full_subscription = stripe.Subscription.retrieve(subscription.id)
                    current_period_end = getattr(full_subscription, 'current_period_end', None)
                    if current_period_end:
                        logger.debug(f"Retrieved current_period_end from full subscription: {current_period_end}")
                    else:
                        logger.warning(f"current_period_end still not available after retrieving full subscription for {subscription.id}")
                except Exception as retrieve_error:
                    logger.warning(f"Failed to retrieve full subscription details: {retrieve_error}")
            
            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "current_period_end": current_period_end,
                "cancel_at_period_end": getattr(subscription, 'cancel_at_period_end', False),
                "latest_invoice_id": subscription.latest_invoice if hasattr(subscription, 'latest_invoice') else None
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
            
            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "canceled_at": subscription.canceled_at if hasattr(subscription, 'canceled_at') else None,
                "metadata": subscription.metadata
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
        Cancels a Stripe subscription at the end of the current period.
        
        Args:
            subscription_id: The Stripe subscription ID to cancel
            
        Returns:
            Dictionary with cancellation details or None if error
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None
            
        try:
            # Cancel at period end to allow user to use remaining time
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
            
            logger.info(f"Stripe subscription {subscription_id} scheduled for cancellation at period end")
            
            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "cancel_at_period_end": subscription.cancel_at_period_end,
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

    async def close(self):
        logger.info("StripeService close called.")
        pass
