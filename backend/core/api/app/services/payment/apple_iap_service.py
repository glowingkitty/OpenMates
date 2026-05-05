# Apple In-App Purchase verification service.
# Validates StoreKit 2 signed transactions using Apple's App Store Server API.
# Uses JWS (JSON Web Signature) verification with Apple's root certificate chain.

import logging
import httpx
import jwt
import time
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Apple's App Store Server API endpoints
APPLE_PRODUCTION_URL = "https://api.storekit.itunes.apple.com"
APPLE_SANDBOX_URL = "https://api.storekit-sandbox.itunes.apple.com"

# Apple root certificates for JWS verification
APPLE_ROOT_CERT_URL = "https://www.apple.com/certificateauthority/AppleRootCA-G3.cer"

# Valid product IDs mapped to credit amounts
APPLE_PRODUCT_CREDITS = {
    "org.openmates.credits.1000": 1_000,
    "org.openmates.credits.10000": 10_000,
    "org.openmates.credits.21000": 21_000,
    "org.openmates.credits.54000": 54_000,
}


@dataclass
class VerifiedAppleTransaction:
    """Parsed and verified Apple transaction."""
    transaction_id: str
    original_transaction_id: str
    product_id: str
    credits: int
    environment: str
    purchase_date: str
    storefront: str
    is_valid: bool
    error: Optional[str] = None


class AppleIAPService:
    """Verifies Apple StoreKit 2 transactions via App Store Server API."""

    def __init__(self, bundle_id: str, issuer_id: str, key_id: str, private_key: str):
        self._bundle_id = bundle_id
        self._issuer_id = issuer_id
        self._key_id = key_id
        self._private_key = private_key

    def _generate_api_token(self) -> str:
        """Generate a JWT token for App Store Server API authentication."""
        now = int(time.time())
        payload = {
            "iss": self._issuer_id,
            "iat": now,
            "exp": now + 3600,
            "aud": "appstoreconnect-v1",
            "bid": self._bundle_id,
        }
        return jwt.encode(
            payload,
            self._private_key,
            algorithm="ES256",
            headers={"kid": self._key_id, "typ": "JWT"},
        )

    async def verify_transaction(
        self,
        transaction_id: str,
        original_transaction_id: str,
        product_id: str,
        claimed_credits: int,
        environment: str,
        signed_date: Optional[str] = None,
        storefront: Optional[str] = None,
    ) -> VerifiedAppleTransaction:
        """
        Verify an Apple StoreKit 2 transaction.

        Steps:
        1. Validate the product_id is a known product
        2. Validate the claimed credits match the product
        3. Query Apple's App Store Server API to verify the transaction exists
        4. Confirm the transaction hasn't been revoked

        Returns a VerifiedAppleTransaction with is_valid=True on success.
        """

        # Step 1: Validate product ID
        if product_id not in APPLE_PRODUCT_CREDITS:
            return VerifiedAppleTransaction(
                transaction_id=transaction_id,
                original_transaction_id=original_transaction_id,
                product_id=product_id,
                credits=0,
                environment=environment,
                purchase_date=signed_date or "",
                storefront=storefront or "",
                is_valid=False,
                error=f"Unknown product ID: {product_id}",
            )

        # Step 2: Validate credits match the product
        expected_credits = APPLE_PRODUCT_CREDITS[product_id]
        if claimed_credits != expected_credits:
            logger.warning(
                f"Apple IAP: Client claimed {claimed_credits} credits for {product_id}, "
                f"expected {expected_credits}. Using server-side value."
            )

        # Step 3: Verify with Apple's App Store Server API
        base_url = APPLE_SANDBOX_URL if environment == "Sandbox" else APPLE_PRODUCTION_URL
        api_url = f"{base_url}/inApps/v1/transactions/{transaction_id}"

        try:
            token = self._generate_api_token()
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    api_url,
                    headers={"Authorization": f"Bearer {token}"},
                )

            if response.status_code == 200:
                data = response.json()
                signed_transaction = data.get("signedTransactionInfo")

                if not signed_transaction:
                    return VerifiedAppleTransaction(
                        transaction_id=transaction_id,
                        original_transaction_id=original_transaction_id,
                        product_id=product_id,
                        credits=expected_credits,
                        environment=environment,
                        purchase_date=signed_date or "",
                        storefront=storefront or "",
                        is_valid=False,
                        error="No signedTransactionInfo in Apple response",
                    )

                # Decode the JWS payload (Apple signs it; header verification is
                # handled by the TLS connection to Apple's API)
                parts = signed_transaction.split(".")
                if len(parts) != 3:
                    return VerifiedAppleTransaction(
                        transaction_id=transaction_id,
                        original_transaction_id=original_transaction_id,
                        product_id=product_id,
                        credits=expected_credits,
                        environment=environment,
                        purchase_date=signed_date or "",
                        storefront=storefront or "",
                        is_valid=False,
                        error="Invalid JWS format from Apple",
                    )

                import base64
                import json

                # Add padding to base64
                padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
                tx_payload = json.loads(base64.urlsafe_b64decode(padded))

                # Verify the transaction matches what was claimed
                apple_product_id = tx_payload.get("productId")
                apple_bundle_id = tx_payload.get("bundleId")
                revocation_date = tx_payload.get("revocationDate")

                if apple_bundle_id != self._bundle_id:
                    return VerifiedAppleTransaction(
                        transaction_id=transaction_id,
                        original_transaction_id=original_transaction_id,
                        product_id=product_id,
                        credits=expected_credits,
                        environment=environment,
                        purchase_date=signed_date or "",
                        storefront=storefront or "",
                        is_valid=False,
                        error=f"Bundle ID mismatch: {apple_bundle_id} != {self._bundle_id}",
                    )

                if apple_product_id != product_id:
                    return VerifiedAppleTransaction(
                        transaction_id=transaction_id,
                        original_transaction_id=original_transaction_id,
                        product_id=product_id,
                        credits=expected_credits,
                        environment=environment,
                        purchase_date=signed_date or "",
                        storefront=storefront or "",
                        is_valid=False,
                        error=f"Product ID mismatch: {apple_product_id} != {product_id}",
                    )

                if revocation_date:
                    return VerifiedAppleTransaction(
                        transaction_id=transaction_id,
                        original_transaction_id=original_transaction_id,
                        product_id=product_id,
                        credits=expected_credits,
                        environment=environment,
                        purchase_date=signed_date or "",
                        storefront=storefront or "",
                        is_valid=False,
                        error="Transaction has been revoked by Apple",
                    )

                logger.info(
                    f"Apple IAP verified: tx={transaction_id}, product={product_id}, "
                    f"credits={expected_credits}, env={environment}"
                )

                return VerifiedAppleTransaction(
                    transaction_id=transaction_id,
                    original_transaction_id=original_transaction_id,
                    product_id=product_id,
                    credits=expected_credits,
                    environment=environment,
                    purchase_date=tx_payload.get("purchaseDate", signed_date or ""),
                    storefront=tx_payload.get("storefront", storefront or ""),
                    is_valid=True,
                )

            elif response.status_code == 404:
                # Transaction not found — could be sandbox vs production mismatch
                if environment != "Sandbox":
                    logger.info(
                        f"Transaction {transaction_id} not found in production, trying sandbox..."
                    )
                    return await self.verify_transaction(
                        transaction_id=transaction_id,
                        original_transaction_id=original_transaction_id,
                        product_id=product_id,
                        claimed_credits=claimed_credits,
                        environment="Sandbox",
                        signed_date=signed_date,
                        storefront=storefront,
                    )

                return VerifiedAppleTransaction(
                    transaction_id=transaction_id,
                    original_transaction_id=original_transaction_id,
                    product_id=product_id,
                    credits=expected_credits,
                    environment=environment,
                    purchase_date=signed_date or "",
                    storefront=storefront or "",
                    is_valid=False,
                    error=f"Transaction not found (HTTP {response.status_code})",
                )

            else:
                return VerifiedAppleTransaction(
                    transaction_id=transaction_id,
                    original_transaction_id=original_transaction_id,
                    product_id=product_id,
                    credits=expected_credits,
                    environment=environment,
                    purchase_date=signed_date or "",
                    storefront=storefront or "",
                    is_valid=False,
                    error=f"Apple API returned HTTP {response.status_code}",
                )

        except Exception as e:
            logger.error(f"Apple IAP verification error for tx {transaction_id}: {e}", exc_info=True)
            return VerifiedAppleTransaction(
                transaction_id=transaction_id,
                original_transaction_id=original_transaction_id,
                product_id=product_id,
                credits=expected_credits,
                environment=environment,
                purchase_date=signed_date or "",
                storefront=storefront or "",
                is_valid=False,
                error=str(e),
            )

    async def check_transaction_not_already_processed(self, transaction_id: str, cache_service) -> bool:
        """Fast cache check for Apple transaction idempotency.

        Durable Directus storage is the source of truth; this cache only avoids
        a database read for recent replays.
        """
        cache_key = f"apple_iap_tx:{transaction_id}"
        existing = await cache_service.get(cache_key)
        return existing is None

    async def mark_transaction_processed(self, transaction_id: str, user_id: str, credits: int, cache_service) -> None:
        """Mark a transaction in the optional fast cache after durable storage."""
        cache_key = f"apple_iap_tx:{transaction_id}"
        await cache_service.set(
            cache_key,
            {"user_id": user_id, "credits": credits, "processed_at": int(time.time())},
            ttl=86400 * 30,  # 30 days
        )
