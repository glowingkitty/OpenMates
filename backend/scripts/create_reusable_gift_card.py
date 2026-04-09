#!/usr/bin/env python3
"""
Create a reusable, domain-bound gift card for the hourly prod-smoke test.

This is a one-off bootstrap script — the card only needs to be created once
per environment, then its `code` goes into the `PROD_SMOKE_GIFT_CARD_CODE`
GitHub secret. The card is NEVER deleted on redemption (is_reusable=true) so
every hourly test run grants the configured credit amount to a fresh signup
without draining anything.

The domain restriction (allowed_email_domain) guarantees only emails from our
Mailosaur subdomain can redeem it — see OPE-76 and the exact-match enforcement
in backend/core/api/app/services/directus/gift_card_methods.py.

Usage (run inside the `api` docker container on dev or prod):

    docker exec api python /app/backend/scripts/create_reusable_gift_card.py \\
        --credits 1000 \\
        --domain abc1xyz9.mailosaur.net \\
        --notes "OPE-76 prod smoke card"

Safety: refuses to create a second reusable card for the same domain. Pass
`--force` to override (you almost never want this).
"""
import argparse
import asyncio
import logging
import random
import string
import sys

# Match the docker container layout used by create_admin.py.
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('create_reusable_gift_card')

# Canonical gift card charset — mirrors backend/core/api/app/routes/admin.py
# (uppercase letters and digits, with ambiguous characters O, I, 0, 1 removed).
# Kept inline instead of imported because importing admin.py would pull in the
# full FastAPI router stack, which we don't need in a one-shot CLI.
GIFT_CARD_CHARSET = (
    string.ascii_uppercase.replace('O', '').replace('I', '')
    + string.digits.replace('0', '').replace('1', '')
)


def generate_gift_card_code() -> str:
    """Generate a XXXX-XXXX-XXXX code using the canonical charset."""
    return '-'.join(
        ''.join(random.choices(GIFT_CARD_CHARSET, k=4)) for _ in range(3)
    )


async def find_existing_reusable_card(
    directus_service: DirectusService,
    domain: str,
) -> dict | None:
    """Return the first reusable card already locked to this domain, or None.

    Uses get_all_gift_cards() and filters in Python — the collection is tiny
    (reusable cards are infrastructure-scoped) so fetching all and filtering
    is simpler than building a Directus query string here.
    """
    all_cards = await directus_service.get_all_gift_cards()
    target = domain.strip().lower()
    for card in all_cards:
        if not card.get('is_reusable'):
            continue
        card_domain = (card.get('allowed_email_domain') or '').strip().lower()
        if card_domain == target:
            return card
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(
        description='Create a reusable, domain-bound gift card for prod smoke tests.'
    )
    parser.add_argument(
        '--credits',
        type=int,
        required=True,
        help='Credits granted per redemption (1-50000). A single value covers every future hourly run because reusable cards grant this amount fresh each time.',
    )
    parser.add_argument(
        '--domain',
        type=str,
        required=True,
        help='Exact full email domain allowed to redeem (e.g. abc1xyz9.mailosaur.net). Case-insensitive exact match — NOT a suffix match.',
    )
    parser.add_argument(
        '--notes',
        type=str,
        default='Reusable prod smoke test card (OPE-76). Do not delete.',
        help='Admin notes stored on the card row.',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Create even if a reusable card already exists for this domain.',
    )
    args = parser.parse_args()

    if not (1 <= args.credits <= 50000):
        logger.error('--credits must be between 1 and 50000.')
        return 2
    if '@' in args.domain or '.' not in args.domain:
        logger.error('--domain must be a bare domain like abc1xyz9.mailosaur.net (no @, must contain a dot).')
        return 2

    sm = SecretsManager()
    await sm.initialize()

    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )

    try:
        # Safety guard: avoid accidental duplicates.
        existing = await find_existing_reusable_card(directus_service, args.domain)
        if existing and not args.force:
            logger.error(
                'A reusable gift card already exists for domain %s:\n'
                '  Code:    %s\n'
                '  Credits: %s\n'
                '  ID:      %s\n'
                'Refusing to create a second one. Pass --force to override.',
                args.domain,
                existing.get('code'),
                existing.get('credits_value'),
                existing.get('id'),
            )
            return 1

        # Generate a unique code with a few retries in case of collision.
        # Collisions are astronomically unlikely on an empty/small collection
        # but we keep the retry for symmetry with the admin endpoint.
        code: str | None = None
        for attempt in range(5):
            candidate = generate_gift_card_code()
            if await directus_service.get_gift_card_by_code(candidate) is None:
                code = candidate
                break
            logger.warning('Code collision on attempt %d, retrying...', attempt + 1)
        if code is None:
            logger.error('Failed to generate a unique gift card code after 5 attempts.')
            return 1

        created = await directus_service.create_gift_card(
            code=code,
            credits_value=args.credits,
            purchaser_user_id_hash=None,
            is_reusable=True,
            allowed_email_domain=args.domain,
        )
        if not created:
            logger.error('Directus refused to create the gift card. See logs above.')
            return 1

        # Attach notes as a separate update — matches the admin endpoint
        # pattern so the schema stays consistent.
        try:
            await directus_service.update_item(
                'gift_cards', created['id'], {'notes': args.notes}
            )
        except Exception as notes_err:  # noqa: BLE001 — non-fatal
            logger.warning('Failed to attach notes (non-fatal): %s', notes_err)

        print('')
        print('SUCCESS: Created reusable gift card')
        print(f'  Code:              {code}')
        print(f'  Credits per grant: {args.credits}')
        print(f'  Domain restricted: {args.domain}')
        print(f'  ID:                {created.get("id")}')
        print('')
        print('Next step: add the code to GitHub secrets:')
        print(
            f'  gh secret set PROD_SMOKE_GIFT_CARD_CODE --body "{code}" '
            '--repo glowingkitty/OpenMates'
        )
        return 0

    except Exception as e:  # noqa: BLE001
        logger.error('Error: %s', e, exc_info=True)
        return 1
    finally:
        await sm.aclose()
        await directus_service.close()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
