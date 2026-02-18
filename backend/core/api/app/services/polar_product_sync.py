"""
Polar Product Synchronization Service

On application startup, this service ensures that one Polar product exists
for every credit tier defined in pricing.yml. Products are identified by
their `metadata.credits_amount` field so re-runs are idempotent — existing
products are reused rather than duplicated.

Only USD pricing is used for Polar products. Polar serves the non-EU market
where USD is the universal default. Polar handles local currency display
and tax addition automatically for each buyer's jurisdiction.

Naming convention:
  One-time products: "{credits} OpenMates Credits"
  e.g. "1,000 OpenMates Credits", "21,000 OpenMates Credits"
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

PRICING_CONFIG_PATH = Path("/shared/config/pricing.yml")
POLAR_HTTP_TIMEOUT = 20.0


class PolarProductSync:
    """
    Ensures Polar products stay in sync with pricing.yml at startup.

    Usage:
        sync = PolarProductSync(polar_service)
        product_id_map = await sync.sync_all_products()
        polar_service.set_product_id_map(product_id_map)
    """

    def __init__(self, polar_service: Any) -> None:
        """
        Args:
            polar_service: Initialized PolarService instance
        """
        self.polar_service = polar_service

    async def sync_all_products(self) -> Dict[int, str]:
        """
        Synchronize all credit tiers from pricing.yml with Polar.

        Returns:
            Dict mapping credits_amount (int) → Polar product_id (str).
            Empty dict if sync fails — the service will log errors and
            credit purchases via Polar will be blocked until resolved.
        """
        logger.info("Starting Polar product synchronization...")

        pricing_tiers = self._load_pricing_config()
        if not pricing_tiers:
            logger.error("PolarProductSync: failed to load pricing.yml, skipping sync")
            return {}

        # Fetch all existing Polar products in one request
        existing_products = await self._fetch_all_products()
        if existing_products is None:
            logger.error("PolarProductSync: failed to fetch existing Polar products, skipping sync")
            return {}

        # Build lookup: credits_amount -> existing product ID (from product metadata)
        existing_map: Dict[int, str] = {}
        for product in existing_products:
            metadata = product.get("metadata") or {}
            credits_in_meta = metadata.get("credits_amount")
            if credits_in_meta is not None:
                try:
                    existing_map[int(credits_in_meta)] = product["id"]
                    logger.debug(
                        f"PolarProductSync: found existing product for "
                        f"{credits_in_meta} credits: {product['id']}"
                    )
                except (ValueError, KeyError):
                    pass

        product_id_map: Dict[int, str] = {}
        created = 0
        reused = 0
        errors = 0

        for tier in pricing_tiers:
            credits = tier.get("credits")
            if not credits:
                continue

            usd_price = tier.get("price", {}).get("usd")
            if usd_price is None:
                logger.warning(f"PolarProductSync: no USD price for {credits} credits tier, skipping")
                continue

            # Reuse existing product if found
            if credits in existing_map:
                product_id_map[credits] = existing_map[credits]
                reused += 1
                logger.debug(f"PolarProductSync: reusing existing product for {credits} credits")
                continue

            # Create new product
            product_id = await self._create_product(credits, usd_price)
            if product_id:
                product_id_map[credits] = product_id
                created += 1
                logger.info(f"PolarProductSync: created product for {credits} credits → {product_id}")
            else:
                errors += 1
                logger.error(f"PolarProductSync: failed to create product for {credits} credits")

        logger.info(
            f"Polar product sync complete: {created} created, {reused} reused, {errors} errors. "
            f"Product map has {len(product_id_map)} entries."
        )
        return product_id_map

    def _load_pricing_config(self) -> Optional[List[Dict[str, Any]]]:
        """Load pricing tiers from the shared pricing.yml config file."""
        try:
            with open(PRICING_CONFIG_PATH, "r") as f:
                data = yaml.safe_load(f)
            tiers = data.get("pricingTiers", [])
            logger.info(f"PolarProductSync: loaded {len(tiers)} pricing tiers from {PRICING_CONFIG_PATH}")
            return tiers
        except FileNotFoundError:
            logger.error(f"PolarProductSync: pricing config not found at {PRICING_CONFIG_PATH}")
            return None
        except yaml.YAMLError as exc:
            logger.error(f"PolarProductSync: error parsing pricing config: {exc}")
            return None
        except Exception as exc:
            logger.error(f"PolarProductSync: unexpected error loading pricing config: {exc}", exc_info=True)
            return None

    async def _fetch_all_products(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch all active products from Polar (handles pagination).

        Returns:
            List of product dicts, or None on error
        """
        products: List[Dict[str, Any]] = []
        page = 1
        limit = 100

        try:
            async with httpx.AsyncClient(timeout=POLAR_HTTP_TIMEOUT) as client:
                while True:
                    response = await client.get(
                        f"{self.polar_service._api_base}/products",
                        headers=self.polar_service._get_headers(),
                        params={"page": page, "limit": limit, "is_archived": False},
                    )

                    if not response.is_success:
                        logger.error(
                            f"PolarProductSync: failed to fetch products page {page}. "
                            f"Status: {response.status_code}, Body: {response.text[:300]}"
                        )
                        return None

                    data = response.json()
                    page_items = data.get("items", [])
                    products.extend(page_items)

                    pagination = data.get("pagination", {})
                    if page >= pagination.get("max_page", 1):
                        break
                    page += 1

            logger.info(f"PolarProductSync: fetched {len(products)} existing products from Polar")
            return products

        except httpx.RequestError as exc:
            logger.error(f"PolarProductSync: HTTP error fetching products: {exc}", exc_info=True)
            return None
        except Exception as exc:
            logger.error(f"PolarProductSync: unexpected error fetching products: {exc}", exc_info=True)
            return None

    async def _create_product(self, credits: int, usd_price: float) -> Optional[str]:
        """
        Create a new one-time purchase product in Polar for a credit tier.

        The product is created with:
          - A fixed USD price (in cents)
          - metadata.credits_amount for idempotent lookup on future syncs
          - metadata.product_type = "credit_purchase" for webhook identification

        Args:
            credits: Number of credits (e.g. 21000)
            usd_price: Price in USD (e.g. 30.0)

        Returns:
            Polar product ID string, or None on error
        """
        # Format credits with thousands separator for display (e.g. "21,000")
        formatted_credits = f"{credits:,}"
        product_name = f"{formatted_credits} OpenMates Credits"

        # Price in cents (Polar uses smallest currency unit for USD)
        price_cents = int(round(usd_price * 100))

        payload = {
            "name": product_name,
            "description": f"Purchase {formatted_credits} OpenMates AI credits.",
            "prices": [
                {
                    "type": "one_time",
                    "price_currency": "usd",
                    "price_amount": price_cents,
                }
            ],
            "metadata": {
                "credits_amount": credits,
                "product_type": "credit_purchase",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=POLAR_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{self.polar_service._api_base}/products",
                    headers=self.polar_service._get_headers(),
                    json=payload,
                )

            if response.status_code not in (200, 201):
                logger.error(
                    f"PolarProductSync: failed to create product '{product_name}'. "
                    f"Status: {response.status_code}, Body: {response.text[:400]}"
                )
                return None

            data = response.json()
            product_id = data.get("id")
            if not product_id:
                logger.error(
                    f"PolarProductSync: product creation response missing 'id'. Response: {data}"
                )
                return None

            return product_id

        except httpx.RequestError as exc:
            logger.error(
                f"PolarProductSync: HTTP error creating product for {credits} credits: {exc}",
                exc_info=True,
            )
            return None
        except Exception as exc:
            logger.error(
                f"PolarProductSync: unexpected error creating product for {credits} credits: {exc}",
                exc_info=True,
            )
            return None
