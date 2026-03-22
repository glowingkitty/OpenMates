"""
Stripe Product Synchronization Service

This service automatically creates and updates Stripe products based on the pricing.yml configuration.
It ensures that Stripe products stay in sync with the server's pricing configuration.

Features:
- Creates one-time purchase products for credit packages
- Creates subscription products for monthly auto top-up
- Updates existing products when prices change
- Handles multiple currencies (EUR, USD)
- Logs all operations for audit trail
"""


import logging
import stripe
from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

class StripeProductSync:
    """
    Service for synchronizing Stripe products with pricing configuration.
    """
    
    def __init__(self, stripe_service):
        """
        Initialize the sync service with a Stripe service instance.
        
        Args:
            stripe_service: Initialized StripeService instance
        """
        self.stripe_service = stripe_service
        self.stripe_api = stripe  # Direct access to Stripe API
        
    async def sync_all_products(self) -> Dict[str, Any]:
        """
        Synchronize all products from pricing.yml with Stripe.
        Optimized to fetch all Stripe data once and compare locally.
        
        Returns:
            Dict containing sync results and statistics
        """
        logger.info("Starting optimized Stripe product synchronization...")
        
        try:
            # Load pricing configuration
            pricing_config = await self._load_pricing_config()
            if not pricing_config:
                logger.error("Failed to load pricing configuration")
                return {"success": False, "error": "Failed to load pricing configuration"}
            
            # Fetch all existing Stripe products and prices in one go
            logger.info("Fetching all existing Stripe products and prices...")
            existing_products, existing_prices = await self._fetch_all_stripe_data()
            
            sync_results = {
                "one_time_products": {"created": 0, "updated": 0, "errors": 0},
                "subscription_products": {"created": 0, "updated": 0, "errors": 0},
                "supporter_products": {"created": 0, "updated": 0, "errors": 0},
                "total_operations": 0
            }
            
            # Sync one-time purchase products
            logger.info("Synchronizing one-time purchase products...")
            one_time_results = await self._sync_one_time_products_optimized(pricing_config, existing_products, existing_prices)
            sync_results["one_time_products"] = one_time_results
            
            # Sync subscription products for monthly auto top-up
            logger.info("Synchronizing subscription products...")
            subscription_results = await self._sync_subscription_products_optimized(pricing_config, existing_products, existing_prices)
            sync_results["subscription_products"] = subscription_results

            # Sync supporter contribution products
            logger.info("Synchronizing supporter contribution products...")
            supporter_results = await self._sync_supporter_products_optimized(existing_products, existing_prices)
            sync_results["supporter_products"] = supporter_results
            
            # Calculate totals
            sync_results["total_operations"] = (
                one_time_results["created"] + one_time_results["updated"] + one_time_results["errors"] +
                subscription_results["created"] + subscription_results["updated"] + subscription_results["errors"] +
                supporter_results["created"] + supporter_results["updated"] + supporter_results["errors"]
            )
            
            logger.info(f"Optimized Stripe product synchronization completed. "
                       f"One-time: {one_time_results['created']} created, {one_time_results['updated']} updated, {one_time_results['errors']} errors. "
                       f"Subscriptions: {subscription_results['created']} created, {subscription_results['updated']} updated, {subscription_results['errors']} errors. "
                       f"Supporter: {supporter_results['created']} created, {supporter_results['updated']} updated, {supporter_results['errors']} errors.")
            
            return {"success": True, "results": sync_results}
            
        except Exception as e:
            logger.error(f"Error during Stripe product synchronization: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def _load_pricing_config(self) -> Optional[Dict[str, Any]]:
        """
        Load pricing configuration from YAML file.
        
        Returns:
            Pricing configuration dictionary or None if failed
        """
        try:
            # Use the Docker mount path
            pricing_file = Path("/shared/config/pricing.yml")
            
            if not pricing_file.exists():
                logger.error(f"Pricing configuration file not found at: {pricing_file}")
                return None
            
            with open(pricing_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            logger.info(f"Loaded pricing configuration from {pricing_file}")
            return config
            
        except Exception as e:
            logger.error(f"Failed to load pricing configuration: {str(e)}", exc_info=True)
            return None
    
    async def _fetch_all_stripe_data(self) -> tuple[Dict[str, Any], Dict[str, List[Any]]]:
        """
        Fetch all existing Stripe products and prices in one go.
        
        Returns:
            Tuple of (products_dict, prices_dict) where:
            - products_dict: {product_name: product_object}
            - prices_dict: {product_id: [price_objects]}
        """
        try:
            # Fetch all active products
            products = self.stripe_api.Product.list(active=True, limit=100)
            products_dict = {}
            prices_dict = {}
            
            logger.info(f"Found {len(products.data)} active products in Stripe")
            
            # Organize products by name for easy lookup
            for product in products.data:
                products_dict[product.name] = product
                prices_dict[product.id] = []
            
            # Fetch all prices for all products
            all_prices = self.stripe_api.Price.list(active=True, limit=100)
            logger.info(f"Found {len(all_prices.data)} active prices in Stripe")
            
            # Organize prices by product ID
            for price in all_prices.data:
                if price.product in prices_dict:
                    prices_dict[price.product].append(price)
            
            return products_dict, prices_dict
            
        except Exception as e:
            logger.error(f"Error fetching Stripe data: {str(e)}", exc_info=True)
            return {}, {}
    
    async def _sync_one_time_products_optimized(self, pricing_config: Dict[str, Any], existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> Dict[str, int]:
        """
        Synchronize one-time purchase products using pre-fetched data.
        
        Args:
            pricing_config: Loaded pricing configuration
            existing_products: Dict of existing products by name
            existing_prices: Dict of existing prices by product ID
            
        Returns:
            Dictionary with sync statistics
        """
        results = {"created": 0, "updated": 0, "errors": 0}
        pricing_tiers = pricing_config.get("pricingTiers", [])
        
        for tier in pricing_tiers:
            credits = tier.get("credits")
            if not credits:
                logger.warning("Skipping tier without credits")
                continue
            
            # Create/update product for each currency
            # JPY removed: Stripe is only used for EU/EEA users; non-EU users go through Polar
            for currency in ["eur", "usd"]:
                price = tier.get("price", {}).get(currency)
                if not price:
                    logger.warning(f"No price found for {currency} in tier {credits} credits")
                    continue
                
                try:
                    result = await self._sync_one_time_product_optimized(credits, currency, price, existing_products, existing_prices)
                    if result == "created":
                        results["created"] += 1
                    elif result == "updated":
                        results["updated"] += 1
                    else:
                        results["errors"] += 1
                except Exception as e:
                    logger.error(f"Error syncing one-time product for {credits} credits in {currency}: {str(e)}")
                    results["errors"] += 1
        
        return results
    
    async def _sync_one_time_product_optimized(self, credits: int, currency: str, price: float, existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> str:
        """
        Create or update a single one-time purchase product using pre-fetched data.
        
        Args:
            credits: Number of credits
            currency: Currency code (eur, usd)
            price: Price in the currency
            existing_products: Dict of existing products by name
            existing_prices: Dict of existing prices by product ID
            
        Returns:
            "created" if new product was created, "updated" if existing product was updated, "error" if failed
        """
        try:
            # Convert price to smallest currency unit
            if currency.lower() == 'jpy':
                price_cents = int(price)
            else:
                price_cents = int(price * 100)
            
            # Create product name with European number format
            product_name = f"{credits:,}".replace(",", ".") + " credits"
            
            # Check if product already exists
            existing_product = existing_products.get(product_name)
            
            if existing_product:
                logger.debug(f"Found existing product: {product_name} (ID: {existing_product.id})")
                # Check if product needs updating
                needs_update = await self._check_one_time_product_needs_update(existing_product, currency, price_cents, credits, existing_prices)
                
                if needs_update:
                    await self._update_one_time_product_optimized(existing_product, currency, price_cents, credits, existing_prices)
                    logger.info(f"Updated existing product: {product_name} ({currency.upper()})")
                    return "updated"
                else:
                    logger.debug(f"Product {product_name} ({currency.upper()}) is already up to date")
                    return "updated"  # Consider it updated since it's correct
            else:
                logger.info(f"No existing product found for: {product_name}")
                # Create new product
                await self._create_one_time_product_optimized(product_name, currency, price_cents, credits)
                logger.info(f"Created new product: {product_name} ({currency.upper()})")
                return "created"
                
        except Exception as e:
            logger.error(f"Error syncing one-time product for {credits} credits in {currency}: {str(e)}")
            raise
    
    async def _check_one_time_product_needs_update(self, product: Any, currency: str, price_cents: int, credits: int, existing_prices: Dict[str, List[Any]]) -> bool:
        """
        Check if a one-time product needs updating by comparing with existing data.
        
        Returns:
            True if product needs updating, False otherwise
        """
        try:
            # Check product metadata (product metadata should not be currency-specific)
            current_metadata = product.metadata or {}
            expected_product_metadata = {
                "credits": str(credits),
                "sync_source": "pricing_yml"
            }
            
            # Check if product metadata needs updating
            for key, expected_value in expected_product_metadata.items():
                if current_metadata.get(key) != expected_value:
                    logger.debug(f"Product metadata mismatch for {product.name}: {key} = {current_metadata.get(key)} != {expected_value}")
                    return True
            
            # Check if price needs updating
            product_prices = existing_prices.get(product.id, [])
            for price in product_prices:
                if price.currency == currency:
                    if price.unit_amount != price_cents:
                        logger.debug(f"Price mismatch for {product.name} ({currency}): {price.unit_amount} != {price_cents}")
                        return True
                    
                    # Check price metadata (price metadata should include currency)
                    price_metadata = price.metadata or {}
                    expected_price_metadata = {
                        "credits": str(credits),
                        "currency": currency,
                        "sync_source": "pricing_yml"
                    }
                    for key, expected_value in expected_price_metadata.items():
                        if price_metadata.get(key) != expected_value:
                            logger.debug(f"Price metadata mismatch for {product.name} ({currency}): {key} = {price_metadata.get(key)} != {expected_value}")
                            return True
                    break
            else:
                # No price found for this currency
                logger.debug(f"No price found for {product.name} in {currency}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking if product {product.name} needs update: {str(e)}")
            return True  # Assume it needs updating if we can't check
    
    async def _update_one_time_product_optimized(self, product: Any, currency: str, price_cents: int, credits: int, existing_prices: Dict[str, List[Any]]) -> bool:
        """
        Update an existing one-time product using pre-fetched data.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update product metadata (product metadata should not be currency-specific)
            self.stripe_api.Product.modify(
                product.id,
                metadata={
                    "credits": str(credits),
                    "sync_source": "pricing_yml"
                }
            )
            logger.info(f"Updated product metadata for {product.name}")
            
            # Update or create price
            product_prices = existing_prices.get(product.id, [])
            existing_price = None
            for price in product_prices:
                if price.currency == currency:
                    existing_price = price
                    break
            
            if existing_price:
                if existing_price.unit_amount != price_cents:
                    # Archive old price and create new one
                    self.stripe_api.Price.modify(existing_price.id, active=False)
                    self.stripe_api.Price.create(
                        product=product.id,
                        unit_amount=price_cents,
                        currency=currency,
                        metadata={
                            "credits": str(credits),
                            "currency": currency,
                            "sync_source": "pricing_yml"
                        }
                    )
                    logger.info(f"Updated price for {product.name} ({currency.upper()}): {price_cents/100:.2f}")
                else:
                    # Update price metadata
                    self.stripe_api.Price.modify(
                        existing_price.id,
                        metadata={
                            "credits": str(credits),
                            "currency": currency,
                            "sync_source": "pricing_yml"
                        }
                    )
                    logger.info(f"Updated price metadata for {product.name} ({currency.upper()})")
            else:
                # Create new price
                self.stripe_api.Price.create(
                    product=product.id,
                    unit_amount=price_cents,
                    currency=currency,
                    metadata={
                        "credits": str(credits),
                        "currency": currency,
                        "sync_source": "pricing_yml"
                    }
                )
                logger.info(f"Created new price for {product.name} ({currency.upper()}): {price_cents/100:.2f}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating product {product.name}: {str(e)}")
            return False
    
    async def _create_one_time_product_optimized(self, name: str, currency: str, price_cents: int, credits: int) -> bool:
        """
        Create a new one-time product using optimized approach.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create the product
            product = self.stripe_api.Product.create(
                name=name,
                description=f"{credits:,} credits for OpenMates AI platform",
                type="service",
                metadata={
                    "credits": str(credits),
                    "sync_source": "pricing_yml"
                }
            )
            
            # Create the price
            self.stripe_api.Price.create(
                product=product.id,
                unit_amount=price_cents,
                currency=currency,
                metadata={
                    "credits": str(credits),
                    "currency": currency,
                    "sync_source": "pricing_yml"
                }
            )
            
            logger.info(f"Created one-time product '{name}' with price {currency.upper()} {price_cents/100:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating one-time product '{name}': {str(e)}")
            return False
    
    async def _sync_subscription_products_optimized(self, pricing_config: Dict[str, Any], existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> Dict[str, int]:
        """
        Synchronize subscription products using pre-fetched data.
        
        Args:
            pricing_config: Loaded pricing configuration
            existing_products: Dict of existing products by name
            existing_prices: Dict of existing prices by product ID
            
        Returns:
            Dictionary with sync statistics
        """
        results = {"created": 0, "updated": 0, "errors": 0}
        pricing_tiers = pricing_config.get("pricingTiers", [])
        
        # Find all tiers that support monthly auto top-up
        subscription_tiers = []
        for tier in pricing_tiers:
            if tier.get("monthly_auto_top_up_extra_credits") is not None:
                credits = tier.get("credits")
                if credits:
                    # Calculate total credits (base + extra)
                    extra_credits = tier.get("monthly_auto_top_up_extra_credits", 0)
                    total_credits = credits + extra_credits
                    
                    # Create subscription config for each currency
                    # JPY removed: Stripe is only used for EU/EEA users; non-EU users go through Polar
                    for currency in ["eur", "usd"]:
                        price = tier.get("price", {}).get(currency)
                        if price is not None:
                            subscription_tiers.append({
                                "credits": total_credits,
                                "base_credits": credits,
                                "extra_credits": extra_credits,
                                "currency": currency,
                                "price": price
                            })
        
        logger.info(f"Found {len(subscription_tiers)} subscription tiers to sync")
        
        for tier in subscription_tiers:
            try:
                result = await self._sync_subscription_product_optimized(
                    tier["credits"], 
                    tier["currency"], 
                    tier["price"],
                    tier["base_credits"],
                    tier["extra_credits"],
                    existing_products,
                    existing_prices
                )
                if result == "created":
                    results["created"] += 1
                elif result == "updated":
                    results["updated"] += 1
                else:
                    results["errors"] += 1
            except Exception as e:
                logger.error(f"Error syncing subscription product for {tier['credits']} credits in {tier['currency']}: {str(e)}")
                results["errors"] += 1
        
        return results
    
    async def _sync_subscription_product_optimized(self, credits: int, currency: str, price: float, base_credits: int, extra_credits: int, existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> str:
        """
        Create or update a subscription product using pre-fetched data.
        
        Args:
            credits: Total number of credits (base + extra)
            currency: Currency code
            price: Price in the currency
            base_credits: Base credits from the tier
            extra_credits: Extra credits for monthly auto top-up
            existing_products: Dict of existing products by name
            existing_prices: Dict of existing prices by product ID
            
        Returns:
            "created" if new product was created, "updated" if existing product was updated, "error" if failed
        """
        try:
            # Convert price to smallest currency unit
            if currency.lower() == 'jpy':
                price_cents = int(price)
            else:
                price_cents = int(price * 100)
            
            # Create product name with European number format
            total_credits_formatted = f"{credits:,}".replace(",", ".")
            product_name = f"{total_credits_formatted} credits (monthly auto top-up)"
            
            # Check if product already exists
            existing_product = existing_products.get(product_name)
            
            if existing_product:
                logger.debug(f"Found existing subscription product: {product_name} (ID: {existing_product.id})")
                # Check if product needs updating
                needs_update = await self._check_subscription_product_needs_update(existing_product, currency, price_cents, base_credits, extra_credits, existing_prices)
                
                if needs_update:
                    await self._update_subscription_product_optimized(existing_product, currency, price_cents, base_credits, extra_credits, existing_prices)
                    logger.info(f"Updated existing subscription product: {product_name} ({currency.upper()})")
                    return "updated"
                else:
                    logger.debug(f"Subscription product {product_name} ({currency.upper()}) is already up to date")
                    return "updated"  # Consider it updated since it's correct
            else:
                logger.info(f"No existing subscription product found for: {product_name}")
                # Create new subscription product
                await self._create_subscription_product_optimized(product_name, currency, price_cents, base_credits, extra_credits)
                logger.info(f"Created new subscription product: {product_name} ({currency.upper()})")
                return "created"
                
        except Exception as e:
            logger.error(f"Error syncing subscription product for {credits} credits in {currency}: {str(e)}")
            raise
    
    async def _check_subscription_product_needs_update(self, product: Any, currency: str, price_cents: int, base_credits: int, extra_credits: int, existing_prices: Dict[str, List[Any]]) -> bool:
        """
        Check if a subscription product needs updating by comparing with existing data.
        
        Returns:
            True if product needs updating, False otherwise
        """
        try:
            total_credits = base_credits + extra_credits
            
            # Check product metadata (product metadata should not be currency-specific)
            current_metadata = product.metadata or {}
            expected_product_metadata = {
                "base_credits": str(base_credits),
                "extra_credits": str(extra_credits),
                "total_credits": str(total_credits),
                "sync_source": "pricing_yml",
                "subscription_type": "monthly_auto_topup"
            }
            
            # Check if product metadata needs updating
            for key, expected_value in expected_product_metadata.items():
                if current_metadata.get(key) != expected_value:
                    logger.debug(f"Subscription product metadata mismatch for {product.name}: {key} = {current_metadata.get(key)} != {expected_value}")
                    return True
            
            # Check if price needs updating
            product_prices = existing_prices.get(product.id, [])
            for price in product_prices:
                if price.currency == currency and price.recurring:
                    if price.unit_amount != price_cents:
                        logger.debug(f"Subscription price mismatch for {product.name} ({currency}): {price.unit_amount} != {price_cents}")
                        return True
                    
                    # Check price metadata (price metadata should include currency)
                    price_metadata = price.metadata or {}
                    expected_price_metadata = {
                        "base_credits": str(base_credits),
                        "extra_credits": str(extra_credits),
                        "total_credits": str(total_credits),
                        "currency": currency,
                        "sync_source": "pricing_yml",
                        "subscription_type": "monthly_auto_topup"
                    }
                    for key, expected_value in expected_price_metadata.items():
                        if price_metadata.get(key) != expected_value:
                            logger.debug(f"Subscription price metadata mismatch for {product.name} ({currency}): {key} = {price_metadata.get(key)} != {expected_value}")
                            return True
                    break
            else:
                # No recurring price found for this currency
                logger.debug(f"No recurring price found for {product.name} in {currency}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking if subscription product {product.name} needs update: {str(e)}")
            return True  # Assume it needs updating if we can't check
    
    async def _update_subscription_product_optimized(self, product: Any, currency: str, price_cents: int, base_credits: int, extra_credits: int, existing_prices: Dict[str, List[Any]]) -> bool:
        """
        Update an existing subscription product using pre-fetched data.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            total_credits = base_credits + extra_credits
            
            # Update product metadata (product metadata should not be currency-specific)
            self.stripe_api.Product.modify(
                product.id,
                metadata={
                    "base_credits": str(base_credits),
                    "extra_credits": str(extra_credits),
                    "total_credits": str(total_credits),
                    "sync_source": "pricing_yml",
                    "subscription_type": "monthly_auto_topup"
                }
            )
            logger.info(f"Updated subscription product metadata for {product.name}")
            
            # Update or create price
            product_prices = existing_prices.get(product.id, [])
            existing_price = None
            for price in product_prices:
                if price.currency == currency and price.recurring:
                    existing_price = price
                    break
            
            if existing_price:
                if existing_price.unit_amount != price_cents:
                    # Archive old price and create new one
                    self.stripe_api.Price.modify(existing_price.id, active=False)
                    self.stripe_api.Price.create(
                        product=product.id,
                        unit_amount=price_cents,
                        currency=currency,
                        recurring={"interval": "month"},
                        metadata={
                            "base_credits": str(base_credits),
                            "extra_credits": str(extra_credits),
                            "total_credits": str(total_credits),
                            "currency": currency,
                            "sync_source": "pricing_yml",
                            "subscription_type": "monthly_auto_topup"
                        }
                    )
                    logger.info(f"Updated subscription price for {product.name} ({currency.upper()}): {price_cents/100:.2f}")
                else:
                    # Update price metadata
                    self.stripe_api.Price.modify(
                        existing_price.id,
                        metadata={
                            "base_credits": str(base_credits),
                            "extra_credits": str(extra_credits),
                            "total_credits": str(total_credits),
                            "currency": currency,
                            "sync_source": "pricing_yml",
                            "subscription_type": "monthly_auto_topup"
                        }
                    )
                    logger.info(f"Updated subscription price metadata for {product.name} ({currency.upper()})")
            else:
                # Create new recurring price
                self.stripe_api.Price.create(
                    product=product.id,
                    unit_amount=price_cents,
                    currency=currency,
                    recurring={"interval": "month"},
                    metadata={
                        "base_credits": str(base_credits),
                        "extra_credits": str(extra_credits),
                        "total_credits": str(total_credits),
                        "currency": currency,
                        "sync_source": "pricing_yml",
                        "subscription_type": "monthly_auto_topup"
                    }
                )
                logger.info(f"Created new subscription price for {product.name} ({currency.upper()}): {price_cents/100:.2f}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating subscription product {product.name}: {str(e)}")
            return False
    
    async def _create_subscription_product_optimized(self, name: str, currency: str, price_cents: int, base_credits: int, extra_credits: int) -> bool:
        """
        Create a new subscription product using optimized approach.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            total_credits = base_credits + extra_credits
            
            # Create the product
            product = self.stripe_api.Product.create(
                name=name,
                description=f"Monthly auto top-up: {base_credits:,} credits + {extra_credits:,} bonus credits = {total_credits:,} total credits for OpenMates AI platform",
                type="service",
                metadata={
                    "base_credits": str(base_credits),
                    "extra_credits": str(extra_credits),
                    "total_credits": str(total_credits),
                    "sync_source": "pricing_yml",
                    "subscription_type": "monthly_auto_topup"
                }
            )
            
            # Create the recurring price
            self.stripe_api.Price.create(
                product=product.id,
                unit_amount=price_cents,
                currency=currency,
                recurring={"interval": "month"},
                metadata={
                    "base_credits": str(base_credits),
                    "extra_credits": str(extra_credits),
                    "total_credits": str(total_credits),
                    "currency": currency,
                    "sync_source": "pricing_yml",
                    "subscription_type": "monthly_auto_topup"
                }
            )
            
            logger.info(f"Created subscription product '{name}' with monthly price {currency.upper()} {price_cents/100:.2f} ({base_credits:,} + {extra_credits:,} = {total_credits:,} credits)")
            return True
            
        except Exception as e:
            logger.error(f"Error creating subscription product '{name}': {str(e)}")
            return False
    
    async def _sync_one_time_product(self, credits: int, currency: str, price: float) -> str:
        """
        Create or update a single one-time purchase product.
        
        Args:
            credits: Number of credits
            currency: Currency code (eur, usd, jpy)
            price: Price in the currency
            
        Returns:
            "created" if new product was created, "updated" if existing product was updated, "error" if failed
        """
        try:
            # Convert price to smallest currency unit
            # EUR and USD use cents (multiply by 100), JPY uses yen (no conversion)
            if currency.lower() == 'jpy':
                price_cents = int(price)
            else:
                price_cents = int(price * 100)
            
            # Create product name and description with European number format
            product_name = f"{credits:,}".replace(",", ".") + " credits"
            product_description = f"{credits:,} credits for OpenMates AI platform"
            
            # Check if product already exists
            existing_product = await self._find_product_by_name(product_name)
            
            if existing_product:
                logger.info(f"Found existing product: {product_name} (ID: {existing_product.id})")
                # Update existing product
                await self._update_product_prices(existing_product, currency, price_cents, credits)
                logger.info(f"Updated existing product: {product_name} ({currency.upper()})")
                return "updated"
            else:
                logger.info(f"No existing product found for: {product_name}")
                # Create new product
                await self._create_one_time_product(product_name, product_description, currency, price_cents, credits)
                logger.info(f"Created new product: {product_name} ({currency.upper()})")
                return "created"
                
        except Exception as e:
            logger.error(f"Error syncing one-time product for {credits} credits in {currency}: {str(e)}")
            raise
    
    async def _sync_subscription_products(self, pricing_config: Dict[str, Any]) -> Dict[str, int]:
        """
        Synchronize subscription products for monthly auto top-up.
        Creates subscription products for all tiers that have monthly_auto_top_up_extra_credits set.
        
        Args:
            pricing_config: Loaded pricing configuration
            
        Returns:
            Dictionary with sync statistics
        """
        results = {"created": 0, "updated": 0, "errors": 0}
        pricing_tiers = pricing_config.get("pricingTiers", [])
        
        # Find all tiers that support monthly auto top-up
        subscription_tiers = []
        for tier in pricing_tiers:
            if tier.get("monthly_auto_top_up_extra_credits") is not None:
                credits = tier.get("credits")
                if credits:
                    # Calculate total credits (base + extra)
                    extra_credits = tier.get("monthly_auto_top_up_extra_credits", 0)
                    total_credits = credits + extra_credits
                    
                    # Create subscription config for each currency
                    # JPY removed: Stripe is only used for EU/EEA users; non-EU users go through Polar
                    for currency in ["eur", "usd"]:
                        price = tier.get("price", {}).get(currency)
                        if price is not None:
                            subscription_tiers.append({
                                "credits": total_credits,
                                "base_credits": credits,
                                "extra_credits": extra_credits,
                                "currency": currency,
                                "price": price
                            })
        
        logger.info(f"Found {len(subscription_tiers)} subscription tiers to sync")
        
        for tier in subscription_tiers:
            try:
                result = await self._sync_subscription_product(
                    tier["credits"], 
                    tier["currency"], 
                    tier["price"],
                    tier["base_credits"],
                    tier["extra_credits"]
                )
                if result == "created":
                    results["created"] += 1
                elif result == "updated":
                    results["updated"] += 1
                else:
                    results["errors"] += 1
            except Exception as e:
                logger.error(f"Error syncing subscription product for {tier['credits']} credits in {tier['currency']}: {str(e)}")
                results["errors"] += 1
        
        return results
    
    async def _sync_subscription_product(self, credits: int, currency: str, price: float, base_credits: int, extra_credits: int) -> str:
        """
        Create or update a subscription product for monthly auto top-up.
        
        Args:
            credits: Total number of credits (base + extra)
            currency: Currency code
            price: Price in the currency
            base_credits: Base credits from the tier
            extra_credits: Extra credits for monthly auto top-up
            
        Returns:
            "created" if new product was created, "updated" if existing product was updated, "error" if failed
        """
        try:
            # Convert price to smallest currency unit
            # EUR and USD use cents (multiply by 100), JPY uses yen (no conversion)
            if currency.lower() == 'jpy':
                price_cents = int(price)
            else:
                price_cents = int(price * 100)
            
            # Create product name and description with European number format
            total_credits_formatted = f"{credits:,}".replace(",", ".")
            product_name = f"{total_credits_formatted} credits (monthly auto top-up)"
            product_description = f"Monthly auto top-up: {base_credits:,} credits + {extra_credits:,} bonus credits = {credits:,} total credits for OpenMates AI platform"
            
            # Check if product already exists
            existing_product = await self._find_product_by_name(product_name)
            
            if existing_product:
                # Update existing subscription product
                await self._update_subscription_prices(existing_product, currency, price_cents, base_credits, extra_credits)
                logger.info(f"Updated existing subscription product: {product_name} ({currency.upper()})")
                return "updated"
            else:
                # Create new subscription product
                await self._create_subscription_product(product_name, product_description, currency, price_cents, base_credits, extra_credits)
                logger.info(f"Created new subscription product: {product_name} ({currency.upper()})")
                return "created"
                
        except Exception as e:
            logger.error(f"Error syncing subscription product for {credits} credits in {currency}: {str(e)}")
            raise
    
    async def _find_product_by_name(self, product_name: str) -> Optional[Dict[str, Any]]:
        """
        Find a Stripe product by name.
        
        Args:
            product_name: Name of the product to find
            
        Returns:
            Product object if found, None otherwise
        """
        try:
            # Search for products with the exact name
            products = self.stripe_api.Product.list(
                active=True,
                limit=100
            )
            
            logger.debug(f"Searching for product: '{product_name}'")
            logger.debug(f"Found {len(products.data)} active products")
            
            for product in products.data:
                logger.debug(f"Checking product: '{product.name}' (ID: {product.id})")
                if product.name == product_name:
                    logger.debug(f"✅ Found matching product: '{product.name}' (ID: {product.id})")
                    return product
            
            logger.debug(f"❌ No product found with name: '{product_name}'")
            return None
            
        except Exception as e:
            logger.error(f"Error searching for product '{product_name}': {str(e)}")
            return None
    
    async def _create_one_time_product(self, name: str, description: str, currency: str, price_cents: int, credits: int) -> Dict[str, Any]:
        """
        Create a new one-time purchase product in Stripe.
        
        Args:
            name: Product name
            description: Product description
            currency: Currency code
            price_cents: Price in cents
            credits: Number of credits this product provides
            
        Returns:
            Created product object
        """
        try:
            # Create the product
            product = self.stripe_api.Product.create(
                name=name,
                description=description,
                type="service",  # One-time purchase
                metadata={
                    "credits": str(credits),  # Store actual credits amount
                    "currency": currency,
                    "sync_source": "pricing_yml"
                }
            )
            
            # Create the price for this product (result not used; side-effect registers the price in Stripe)
            self.stripe_api.Price.create(
                product=product.id,
                unit_amount=price_cents,
                currency=currency,
                metadata={
                    "credits": str(credits),  # Use actual credits, not price calculation
                    "currency": currency,
                    "sync_source": "pricing_yml"
                }
            )
            
            logger.info(f"Created one-time product '{name}' with price {currency.upper()} {price_cents/100:.2f}")
            return product
            
        except Exception as e:
            logger.error(f"Error creating one-time product '{name}': {str(e)}")
            raise
    
    async def _create_subscription_product(self, name: str, description: str, currency: str, price_cents: int, base_credits: int, extra_credits: int) -> Dict[str, Any]:
        """
        Create a new subscription product in Stripe.
        
        Args:
            name: Product name
            description: Product description
            currency: Currency code
            price_cents: Price in cents
            base_credits: Base credits from the tier
            extra_credits: Extra credits for monthly auto top-up
            
        Returns:
            Created product object
        """
        try:
            total_credits = base_credits + extra_credits
            
            # Create the product
            product = self.stripe_api.Product.create(
                name=name,
                description=description,
                type="service",  # Subscription product
                metadata={
                    "base_credits": str(base_credits),
                    "extra_credits": str(extra_credits),
                    "total_credits": str(total_credits),
                    "currency": currency,
                    "sync_source": "pricing_yml",
                    "subscription_type": "monthly_auto_topup"
                }
            )
            
            # Create the recurring price for this product (result not used; side-effect registers the price in Stripe)
            self.stripe_api.Price.create(
                product=product.id,
                unit_amount=price_cents,
                currency=currency,
                recurring={"interval": "month"},  # Monthly subscription
                metadata={
                    "base_credits": str(base_credits),
                    "extra_credits": str(extra_credits),
                    "total_credits": str(total_credits),
                    "currency": currency,
                    "sync_source": "pricing_yml",
                    "subscription_type": "monthly_auto_topup"
                }
            )
            
            logger.info(f"Created subscription product '{name}' with monthly price {currency.upper()} {price_cents/100:.2f} ({base_credits:,} + {extra_credits:,} = {total_credits:,} credits)")
            return product
            
        except Exception as e:
            logger.error(f"Error creating subscription product '{name}': {str(e)}")
            raise
    
    async def _update_product_prices(self, product: Dict[str, Any], currency: str, price_cents: int, credits: int) -> bool:
        """
        Update prices for an existing product.
        
        Args:
            product: Existing Stripe product
            currency: Currency code
            price_cents: New price in cents
            credits: Number of credits this product provides
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get existing prices for this product
            prices = self.stripe_api.Price.list(
                product=product.id,
                active=True
            )
            
            # Find price for this currency
            existing_price = None
            for price in prices.data:
                if price.currency == currency:
                    existing_price = price
                    break
            
            if existing_price:
                # Check if price needs updating
                if existing_price.unit_amount != price_cents:
                    # Archive old price
                    self.stripe_api.Price.modify(
                        existing_price.id,
                        active=False
                    )
                    
                    # Create new price
                    self.stripe_api.Price.create(
                        product=product.id,
                        unit_amount=price_cents,
                        currency=currency,
                        metadata={
                            "credits": str(credits),
                            "currency": currency,
                            "sync_source": "pricing_yml"
                        }
                    )
                    
                    logger.info(f"Updated price for product '{product.name}' ({currency.upper()}): {price_cents/100:.2f}")
                else:
                    # Price amount is correct, but check if metadata needs updating
                    current_metadata = existing_price.metadata or {}
                    expected_metadata = {
                        "credits": str(credits),
                        "currency": currency,
                        "sync_source": "pricing_yml"
                    }
                    
                    # Check if metadata needs updating
                    metadata_needs_update = False
                    for key, expected_value in expected_metadata.items():
                        if current_metadata.get(key) != expected_value:
                            metadata_needs_update = True
                            break
                    
                    if metadata_needs_update:
                        # Update existing price metadata
                        self.stripe_api.Price.modify(
                            existing_price.id,
                            metadata=expected_metadata
                        )
                        logger.info(f"Updated metadata for existing price '{product.name}' ({currency.upper()})")
                    else:
                        logger.info(f"Price for product '{product.name}' ({currency.upper()}) is already up to date")
            else:
                # Create new price for this currency
                self.stripe_api.Price.create(
                    product=product.id,
                    unit_amount=price_cents,
                    currency=currency,
                    metadata={
                        "credits": str(credits),
                        "currency": currency,
                        "sync_source": "pricing_yml"
                    }
                )
                
                logger.info(f"Created new price for product '{product.name}' ({currency.upper()}): {price_cents/100:.2f}")
            
            # Update product metadata with correct credits
            logger.info(f"Updating product metadata for {product.name} (ID: {product.id}) with credits: {credits}")
            self.stripe_api.Product.modify(
                product.id,
                metadata={
                    "credits": str(credits),
                    "currency": currency,
                    "sync_source": "pricing_yml"
                }
            )
            logger.info(f"✅ Successfully updated product metadata for {product.name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating prices for product '{product.name}': {str(e)}")
            return False
    
    async def _update_subscription_prices(self, product: Dict[str, Any], currency: str, price_cents: int, base_credits: int, extra_credits: int) -> bool:
        """
        Update prices for an existing subscription product.
        
        Args:
            product: Existing Stripe product
            currency: Currency code
            price_cents: New price in cents
            base_credits: Base credits from the tier
            extra_credits: Extra credits for monthly auto top-up
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Calculate total credits at the beginning
            total_credits = base_credits + extra_credits
            
            # Get existing prices for this product
            prices = self.stripe_api.Price.list(
                product=product.id,
                active=True
            )
            
            # Find recurring price for this currency
            existing_price = None
            for price in prices.data:
                if price.currency == currency and price.recurring:
                    existing_price = price
                    break
            
            if existing_price:
                # Check if price needs updating
                if existing_price.unit_amount != price_cents:
                    # Archive old price
                    self.stripe_api.Price.modify(
                        existing_price.id,
                        active=False
                    )
                    
                    # Create new recurring price
                    self.stripe_api.Price.create(
                        product=product.id,
                        unit_amount=price_cents,
                        currency=currency,
                        recurring={"interval": "month"},
                        metadata={
                            "base_credits": str(base_credits),
                            "extra_credits": str(extra_credits),
                            "total_credits": str(total_credits),
                            "currency": currency,
                            "sync_source": "pricing_yml",
                            "subscription_type": "monthly_auto_topup"
                        }
                    )
                    
                    logger.info(f"Updated subscription price for product '{product.name}' ({currency.upper()}): {price_cents/100:.2f}")
                else:
                    # Price amount is correct, but check if metadata needs updating
                    current_metadata = existing_price.metadata or {}
                    expected_metadata = {
                        "base_credits": str(base_credits),
                        "extra_credits": str(extra_credits),
                        "total_credits": str(total_credits),
                        "currency": currency,
                        "sync_source": "pricing_yml",
                        "subscription_type": "monthly_auto_topup"
                    }
                    
                    # Check if metadata needs updating
                    metadata_needs_update = False
                    for key, expected_value in expected_metadata.items():
                        if current_metadata.get(key) != expected_value:
                            metadata_needs_update = True
                            break
                    
                    if metadata_needs_update:
                        # Update existing subscription price metadata
                        self.stripe_api.Price.modify(
                            existing_price.id,
                            metadata=expected_metadata
                        )
                        logger.info(f"Updated metadata for existing subscription price '{product.name}' ({currency.upper()})")
                    else:
                        logger.info(f"Subscription price for product '{product.name}' ({currency.upper()}) is already up to date")
            else:
                # Create new recurring price for this currency
                self.stripe_api.Price.create(
                    product=product.id,
                    unit_amount=price_cents,
                    currency=currency,
                    recurring={"interval": "month"},
                    metadata={
                        "base_credits": str(base_credits),
                        "extra_credits": str(extra_credits),
                        "total_credits": str(total_credits),
                        "currency": currency,
                        "sync_source": "pricing_yml",
                        "subscription_type": "monthly_auto_topup"
                    }
                )
                
                logger.info(f"Created new subscription price for product '{product.name}' ({currency.upper()}): {price_cents/100:.2f}")
            
            # Update product metadata with correct credits
            logger.info(f"Updating subscription product metadata for {product.name} (ID: {product.id}) with base_credits: {base_credits}, extra_credits: {extra_credits}, total_credits: {total_credits}")
            self.stripe_api.Product.modify(
                product.id,
                metadata={
                    "base_credits": str(base_credits),
                    "extra_credits": str(extra_credits),
                    "total_credits": str(total_credits),
                    "currency": currency,
                    "sync_source": "pricing_yml",
                    "subscription_type": "monthly_auto_topup"
                }
            )
            logger.info(f"✅ Successfully updated subscription product metadata for {product.name}")
            
            return True

        except Exception as e:
            logger.error(f"Error updating subscription prices for product '{product.name}': {str(e)}")
            return False

    async def _sync_supporter_products_optimized(self, existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> Dict[str, int]:
        """
        Synchronize supporter contribution products using pre-fetched data.
        Creates 2 products (one-time and monthly) with all price tiers on each product.

        Args:
            existing_products: Dict of existing products by name
            existing_prices: Dict of existing prices by product ID

        Returns:
            Dictionary with sync statistics
        """
        results = {"created": 0, "updated": 0, "errors": 0}

        # Define supporter contribution tiers (€5, €10, €20, €50, €100, €200)
        # Supporter payments always go through Stripe for all users.
        # JPY removed: non-EU users pay via Polar (not Stripe), so JPY is no longer needed.
        supporter_tiers = [5, 10, 20, 50, 100, 200]
        currencies = ["eur", "usd"]

        # Currency conversion rates (approximate)
        eur_to_other = {
            "eur": 1.0,
            "usd": 1.1,
        }

        logger.info(f"Synchronizing supporter products with {len(supporter_tiers)} tiers across {len(currencies)} currencies")

        try:
            # Sync one-time supporter product (with all tiers and currencies as prices)
            one_time_result = await self._sync_supporter_product_with_all_prices(
                "Supporter Contribution",
                "One-time supporter contribution to help fund OpenMates development",
                False,  # not recurring
                supporter_tiers, currencies, eur_to_other, existing_products, existing_prices
            )
            if one_time_result == "created":
                results["created"] += 1
            elif one_time_result == "updated":
                results["updated"] += 1
            else:
                results["errors"] += 1

            # Sync monthly supporter product (with all tiers and currencies as prices)
            monthly_result = await self._sync_supporter_product_with_all_prices(
                "Monthly Supporter Contribution",
                "Monthly recurring supporter contribution to help fund OpenMates development",
                True,  # recurring
                supporter_tiers, currencies, eur_to_other, existing_products, existing_prices
            )
            if monthly_result == "created":
                results["created"] += 1
            elif monthly_result == "updated":
                results["updated"] += 1
            else:
                results["errors"] += 1

        except Exception as e:
            logger.error(f"Error syncing supporter products: {str(e)}")
            results["errors"] += 2

        logger.info(f"Supporter products sync completed: {results['created']} created, {results['updated']} updated, {results['errors']} errors")
        return results

    async def _sync_supporter_product_with_all_prices(self, product_name: str, product_description: str, is_recurring: bool, supporter_tiers: List[int], currencies: List[str], eur_to_other: Dict[str, float], existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> str:
        """
        Create or update a supporter product with ALL price tiers and currencies.

        Args:
            product_name: Name of the product (e.g., "Monthly Supporter Contribution")
            product_description: Description of the product
            is_recurring: True for monthly subscriptions, False for one-time
            supporter_tiers: List of EUR amounts [5, 10, 20, 50, 100, 200]
            currencies: List of currency codes ["eur", "usd"]
            eur_to_other: Currency conversion rates
            existing_products: Dict of existing products by name
            existing_prices: Dict of existing prices by product ID

        Returns:
            "created" if new product was created, "updated" if existing product was updated
        """
        try:
            # Check if product already exists
            existing_product = existing_products.get(product_name)

            if existing_product:
                logger.debug(f"Found existing supporter product: {product_name} (ID: {existing_product.id})")
                # Update the product with all required prices
                await self._update_supporter_product_all_prices(
                    existing_product, is_recurring, supporter_tiers, currencies, eur_to_other, existing_prices
                )
                logger.info(f"Updated supporter product: {product_name} with all price tiers")
                return "updated"
            else:
                logger.info(f"No existing supporter product found: {product_name}")
                # Create new supporter product with all prices
                await self._create_supporter_product_all_prices(
                    product_name, product_description, is_recurring, supporter_tiers, currencies, eur_to_other
                )
                logger.info(f"Created supporter product: {product_name} with all price tiers")
                return "created"

        except Exception as e:
            logger.error(f"Error syncing supporter product {product_name}: {str(e)}")
            raise

    async def _update_supporter_product_all_prices(self, product: Any, is_recurring: bool, supporter_tiers: List[int], currencies: List[str], eur_to_other: Dict[str, float], existing_prices: Dict[str, List[Any]]) -> bool:
        """
        Update an existing supporter product to have all required price tiers.
        """
        try:
            # Update product metadata
            self.stripe_api.Product.modify(
                product.id,
                metadata={
                    "sync_source": "pricing_yml",
                    "product_type": "supporter_contribution",
                    "is_recurring": str(is_recurring)
                }
            )

            # Get existing prices for this product
            product_prices = existing_prices.get(product.id, [])
            existing_prices_map = {}  # {(currency, tier_eur): price_object}

            for price in product_prices:
                if (is_recurring and price.recurring) or (not is_recurring and not price.recurring):
                    # Get tier from metadata
                    tier_eur = price.metadata.get("tier_eur") if price.metadata else None
                    if tier_eur:
                        existing_prices_map[(price.currency, int(tier_eur))] = price

            # Ensure all required prices exist
            for tier_eur in supporter_tiers:
                for currency in currencies:
                    price = tier_eur * eur_to_other[currency]
                    price_cents = int(price * 100) if currency.lower() != 'jpy' else int(price)

                    price_key = (currency, tier_eur)
                    existing_price = existing_prices_map.get(price_key)

                    price_metadata = {
                        "tier_eur": str(tier_eur),
                        "currency": currency,
                        "sync_source": "pricing_yml",
                        "product_type": "supporter_contribution",
                        "is_recurring": str(is_recurring)
                    }

                    if existing_price:
                        # Check if price needs updating
                        if existing_price.unit_amount != price_cents:
                            # Archive old price and create new one
                            self.stripe_api.Price.modify(existing_price.id, active=False)
                            self._create_supporter_price(product.id, currency, price_cents, is_recurring, price_metadata)
                            logger.info(f"Updated price for {product.name} ({currency.upper()}, €{tier_eur}): {price_cents}")
                        else:
                            # Update metadata if needed
                            self.stripe_api.Price.modify(existing_price.id, metadata=price_metadata)
                    else:
                        # Create new price
                        self._create_supporter_price(product.id, currency, price_cents, is_recurring, price_metadata)
                        logger.info(f"Created new price for {product.name} ({currency.upper()}, €{tier_eur}): {price_cents}")

            return True

        except Exception as e:
            logger.error(f"Error updating supporter product {product.name}: {str(e)}")
            return False

    async def _create_supporter_product_all_prices(self, product_name: str, product_description: str, is_recurring: bool, supporter_tiers: List[int], currencies: List[str], eur_to_other: Dict[str, float]) -> bool:
        """
        Create a new supporter product with all price tiers.
        """
        try:
            # Create the product
            product = self.stripe_api.Product.create(
                name=product_name,
                description=product_description,
                type="service",
                metadata={
                    "sync_source": "pricing_yml",
                    "product_type": "supporter_contribution",
                    "is_recurring": str(is_recurring)
                }
            )

            # Create all prices for this product
            for tier_eur in supporter_tiers:
                for currency in currencies:
                    price = tier_eur * eur_to_other[currency]
                    price_cents = int(price * 100) if currency.lower() != 'jpy' else int(price)

                    price_metadata = {
                        "tier_eur": str(tier_eur),
                        "currency": currency,
                        "sync_source": "pricing_yml",
                        "product_type": "supporter_contribution",
                        "is_recurring": str(is_recurring)
                    }

                    self._create_supporter_price(product.id, currency, price_cents, is_recurring, price_metadata)

            recurring_text = "monthly" if is_recurring else "one-time"
            logger.info(f"Created {recurring_text} supporter product '{product_name}' with {len(supporter_tiers) * len(currencies)} prices")
            return True

        except Exception as e:
            logger.error(f"Error creating supporter product '{product_name}': {str(e)}")
            return False

    def _create_supporter_price(self, product_id: str, currency: str, price_cents: int, is_recurring: bool, metadata: Dict[str, str]) -> Any:
        """
        Create a supporter price with appropriate parameters.
        """
        price_params = {
            "product": product_id,
            "unit_amount": price_cents,
            "currency": currency,
            "metadata": metadata
        }

        if is_recurring:
            price_params["recurring"] = {"interval": "month"}

        return self.stripe_api.Price.create(**price_params)

    async def _sync_one_time_supporter_product_optimized(self, tier_eur: int, currency: str, price: float, existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> str:
        """
        Create or update a one-time supporter contribution product.

        Returns:
            "created" if new product was created, "updated" if existing product was updated, "error" if failed
        """
        try:
            # Convert price to smallest currency unit
            if currency.lower() == 'jpy':
                price_cents = int(price)
            else:
                price_cents = int(price * 100)

            # Create product name
            product_name = "Supporter Contribution"

            # Check if product already exists
            existing_product = existing_products.get(product_name)

            if existing_product:
                logger.debug(f"Found existing supporter product: {product_name} (ID: {existing_product.id})")
                # Check if product needs updating for this currency
                needs_update = await self._check_supporter_product_needs_update(
                    existing_product, currency, price_cents, tier_eur, False, existing_prices
                )

                if needs_update:
                    await self._update_supporter_product_optimized(
                        existing_product, currency, price_cents, tier_eur, False, existing_prices
                    )
                    logger.info(f"Updated supporter product: {product_name} ({currency.upper()}, €{tier_eur})")
                    return "updated"
                else:
                    logger.debug(f"Supporter product {product_name} ({currency.upper()}, €{tier_eur}) is already up to date")
                    return "updated"
            else:
                logger.info(f"No existing supporter product found: {product_name}")
                # Create new supporter product
                await self._create_supporter_product_optimized(product_name, currency, price_cents, tier_eur, False)
                logger.info(f"Created supporter product: {product_name} ({currency.upper()}, €{tier_eur})")
                return "created"

        except Exception as e:
            logger.error(f"Error syncing one-time supporter product for €{tier_eur} in {currency}: {str(e)}")
            raise

    async def _sync_monthly_supporter_product_optimized(self, tier_eur: int, currency: str, price: float, existing_products: Dict[str, Any], existing_prices: Dict[str, List[Any]]) -> str:
        """
        Create or update a monthly supporter contribution product.

        Returns:
            "created" if new product was created, "updated" if existing product was updated, "error" if failed
        """
        try:
            # Convert price to smallest currency unit
            if currency.lower() == 'jpy':
                price_cents = int(price)
            else:
                price_cents = int(price * 100)

            # Create product name
            product_name = "Monthly Supporter Contribution"

            # Check if product already exists
            existing_product = existing_products.get(product_name)

            if existing_product:
                logger.debug(f"Found existing monthly supporter product: {product_name} (ID: {existing_product.id})")
                # Check if product needs updating for this currency
                needs_update = await self._check_supporter_product_needs_update(
                    existing_product, currency, price_cents, tier_eur, True, existing_prices
                )

                if needs_update:
                    await self._update_supporter_product_optimized(
                        existing_product, currency, price_cents, tier_eur, True, existing_prices
                    )
                    logger.info(f"Updated monthly supporter product: {product_name} ({currency.upper()}, €{tier_eur})")
                    return "updated"
                else:
                    logger.debug(f"Monthly supporter product {product_name} ({currency.upper()}, €{tier_eur}) is already up to date")
                    return "updated"
            else:
                logger.info(f"No existing monthly supporter product found: {product_name}")
                # Create new monthly supporter product
                await self._create_supporter_product_optimized(product_name, currency, price_cents, tier_eur, True)
                logger.info(f"Created monthly supporter product: {product_name} ({currency.upper()}, €{tier_eur})")
                return "created"

        except Exception as e:
            logger.error(f"Error syncing monthly supporter product for €{tier_eur} in {currency}: {str(e)}")
            raise

    async def _check_supporter_product_needs_update(self, product: Any, currency: str, price_cents: int, tier_eur: int, is_recurring: bool, existing_prices: Dict[str, List[Any]]) -> bool:
        """
        Check if a supporter product needs updating by comparing with existing data.

        Returns:
            True if product needs updating, False otherwise
        """
        try:
            # Check product metadata
            current_metadata = product.metadata or {}
            expected_product_metadata = {
                "sync_source": "pricing_yml",
                "product_type": "supporter_contribution",
                "is_recurring": str(is_recurring)
            }

            # Check if product metadata needs updating
            for key, expected_value in expected_product_metadata.items():
                if current_metadata.get(key) != expected_value:
                    logger.debug(f"Supporter product metadata mismatch for {product.name}: {key} = {current_metadata.get(key)} != {expected_value}")
                    return True

            # Check if price needs updating
            product_prices = existing_prices.get(product.id, [])
            for price in product_prices:
                if price.currency == currency:
                    # For monthly products, check that it's recurring; for one-time, check that it's not
                    if is_recurring and not price.recurring:
                        continue
                    elif not is_recurring and price.recurring:
                        continue

                    if price.unit_amount != price_cents:
                        logger.debug(f"Supporter price mismatch for {product.name} ({currency}): {price.unit_amount} != {price_cents}")
                        return True

                    # Check price metadata
                    price_metadata = price.metadata or {}
                    expected_price_metadata = {
                        "tier_eur": str(tier_eur),
                        "currency": currency,
                        "sync_source": "pricing_yml",
                        "product_type": "supporter_contribution",
                        "is_recurring": str(is_recurring)
                    }
                    for key, expected_value in expected_price_metadata.items():
                        if price_metadata.get(key) != expected_value:
                            logger.debug(f"Supporter price metadata mismatch for {product.name} ({currency}): {key} = {price_metadata.get(key)} != {expected_value}")
                            return True
                    break
            else:
                # No price found for this currency and recurrence type
                logger.debug(f"No price found for {product.name} in {currency} (recurring: {is_recurring})")
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking if supporter product {product.name} needs update: {str(e)}")
            return True  # Assume it needs updating if we can't check

    async def _update_supporter_product_optimized(self, product: Any, currency: str, price_cents: int, tier_eur: int, is_recurring: bool, existing_prices: Dict[str, List[Any]]) -> bool:
        """
        Update an existing supporter product using pre-fetched data.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Update product metadata
            self.stripe_api.Product.modify(
                product.id,
                metadata={
                    "sync_source": "pricing_yml",
                    "product_type": "supporter_contribution",
                    "is_recurring": str(is_recurring)
                }
            )
            logger.info(f"Updated supporter product metadata for {product.name}")

            # Update or create price
            product_prices = existing_prices.get(product.id, [])
            existing_price = None
            for price in product_prices:
                if price.currency == currency:
                    # For monthly products, check that it's recurring; for one-time, check that it's not
                    if is_recurring and price.recurring:
                        existing_price = price
                        break
                    elif not is_recurring and not price.recurring:
                        existing_price = price
                        break

            price_metadata = {
                "tier_eur": str(tier_eur),
                "currency": currency,
                "sync_source": "pricing_yml",
                "product_type": "supporter_contribution",
                "is_recurring": str(is_recurring)
            }

            if existing_price:
                if existing_price.unit_amount != price_cents:
                    # Archive old price and create new one
                    self.stripe_api.Price.modify(existing_price.id, active=False)

                    price_params = {
                        "product": product.id,
                        "unit_amount": price_cents,
                        "currency": currency,
                        "metadata": price_metadata
                    }

                    if is_recurring:
                        price_params["recurring"] = {"interval": "month"}

                    self.stripe_api.Price.create(**price_params)
                    logger.info(f"Updated supporter price for {product.name} ({currency.upper()}): {price_cents/100:.2f}")
                else:
                    # Update price metadata
                    self.stripe_api.Price.modify(existing_price.id, metadata=price_metadata)
                    logger.info(f"Updated supporter price metadata for {product.name} ({currency.upper()})")
            else:
                # Create new price
                price_params = {
                    "product": product.id,
                    "unit_amount": price_cents,
                    "currency": currency,
                    "metadata": price_metadata
                }

                if is_recurring:
                    price_params["recurring"] = {"interval": "month"}

                self.stripe_api.Price.create(**price_params)
                logger.info(f"Created new supporter price for {product.name} ({currency.upper()}): {price_cents/100:.2f}")

            return True

        except Exception as e:
            logger.error(f"Error updating supporter product {product.name}: {str(e)}")
            return False

    async def _create_supporter_product_optimized(self, name: str, currency: str, price_cents: int, tier_eur: int, is_recurring: bool) -> bool:
        """
        Create a new supporter product using optimized approach.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create description based on type
            if is_recurring:
                description = "Monthly recurring supporter contribution to help fund OpenMates development"
            else:
                description = "One-time supporter contribution to help fund OpenMates development"

            # Create the product
            product = self.stripe_api.Product.create(
                name=name,
                description=description,
                type="service",
                metadata={
                    "sync_source": "pricing_yml",
                    "product_type": "supporter_contribution",
                    "is_recurring": str(is_recurring)
                }
            )

            # Create the price
            price_metadata = {
                "tier_eur": str(tier_eur),
                "currency": currency,
                "sync_source": "pricing_yml",
                "product_type": "supporter_contribution",
                "is_recurring": str(is_recurring)
            }

            price_params = {
                "product": product.id,
                "unit_amount": price_cents,
                "currency": currency,
                "metadata": price_metadata
            }

            if is_recurring:
                price_params["recurring"] = {"interval": "month"}

            self.stripe_api.Price.create(**price_params)

            recurring_text = "monthly" if is_recurring else "one-time"
            logger.info(f"Created {recurring_text} supporter product '{name}' with price {currency.upper()} {price_cents/100:.2f}")
            return True

        except Exception as e:
            logger.error(f"Error creating supporter product '{name}': {str(e)}")
            return False
