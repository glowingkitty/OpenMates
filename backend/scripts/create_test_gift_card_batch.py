"""
Create a batch of single-use TEST gift cards for the regular AI test users.

Redeeming one of these cards gives the account 1000 credits and labels it as a
test account (users.is_test_account), so it never counts in growth numbers or
server stats. These cards must only ever be created by this script, inside the
production api container; no online endpoint can set marks_test_account.

Operator instructions (production, run by the owner):

1. Open a prod SSH window (see .claude/skills/prod-ssh/SKILL.md): on prod run
   `./scripts/temp-ssh-access.sh start "<dev-pubkey>" --minutes 30`, then open
   the master connection from the dev host with `scripts/prod-ssh.sh open`
   (it asks for the TOTP).
2. Check the schema carries the field and see what is left:
       docker exec -i api python /app/backend/scripts/create_test_gift_card_batch.py --count-remaining
3. Create the cards and store the codes on the dev host only (codes go to
   stdout only; nothing is logged or written on prod):
       umask 077; mkdir -p ~/.openmates/ai-test-users
       scripts/prod-ssh.sh "docker exec -i api python /app/backend/scripts/create_test_gift_card_batch.py --count 40" \\
           >> ~/.openmates/ai-test-users/prod-gift-cards.txt
       chmod 600 ~/.openmates/ai-test-users/prod-gift-cards.txt
   Use --dry-run first to see what would be created (no codes printed).
4. Close the window: `scripts/prod-ssh.sh close` and let temp-ssh-access expire.

Options: --count N (1-500), --credits C (default and maximum 1000),
--dry-run, --count-remaining. The script refuses to run when the gift_cards
schema lacks marks_test_account (deploy the schema first).
"""
import argparse
import asyncio
import logging
import random
import string
import sys
from datetime import date

sys.path.insert(0, '/app/backend')

MAX_CREDITS = 1000
MAX_COUNT = 500
GIFT_CARD_CHARSET = (
    string.ascii_uppercase.replace('O', '').replace('I', '')
    + string.digits.replace('0', '').replace('1', '')
)
logger = logging.getLogger('create_test_gift_card_batch')


def generate_gift_card_code() -> str:
    """Generate a XXXX-XXXX-XXXX code using the canonical charset."""
    return '-'.join(''.join(random.SystemRandom().choices(GIFT_CARD_CHARSET, k=4)) for _ in range(3))


def build_card_fields(credits: int, notes: str) -> dict:
    """Fields of one test card beyond code: single-use, capped credits, marking."""
    if not 1 <= credits <= MAX_CREDITS:
        raise ValueError(f'credits must be between 1 and {MAX_CREDITS}')
    return {'credits_value': credits, 'is_reusable': False, 'marks_test_account': True, 'notes': notes}


async def schema_has_marks_test_account(directus) -> bool:
    """True when the gift_cards collection has the marks_test_account field."""
    token = await directus.ensure_auth_token(admin_required=True)
    response = await directus._make_api_request(
        'GET', f'{directus.base_url}/fields/gift_cards/marks_test_account',
        headers={'Authorization': f'Bearer {token}'})
    return response.status_code == 200


async def count_remaining(directus) -> int:
    """Number of unredeemed (not yet deleted) marks_test_account cards."""
    cards = await directus.get_all_gift_cards()
    return sum(1 for card in cards if card.get('marks_test_account'))


async def create_batch(directus, count: int, credits: int, notes: str) -> list[str]:
    """Create ``count`` cards and return their codes. Codes are never logged."""
    fields = build_card_fields(credits, notes)
    codes: list[str] = []
    while len(codes) < count:
        code = generate_gift_card_code()
        if await directus.get_gift_card_by_code(code) is not None:
            continue
        created = await directus.create_gift_card(
            code=code, credits_value=fields['credits_value'], purchaser_user_id_hash=None)
        if not created:
            raise RuntimeError(f'Directus refused to create card {len(codes) + 1}; {len(codes)} created')
        await directus.update_item(
            'gift_cards', created['id'], {'marks_test_account': True, 'notes': fields['notes']})
        codes.append(code)
    return codes


async def main() -> int:
    parser = argparse.ArgumentParser(description='Create single-use test gift cards (marks_test_account).')
    parser.add_argument('--count', type=int, default=0, help=f'Cards to create (1-{MAX_COUNT}).')
    parser.add_argument('--credits', type=int, default=MAX_CREDITS, help=f'Credits per card (max {MAX_CREDITS}).')
    parser.add_argument('--dry-run', action='store_true', help='Validate and report; create nothing.')
    parser.add_argument('--count-remaining', action='store_true', help='Print unredeemed test card count.')
    args = parser.parse_args()
    if not args.count_remaining and not 1 <= args.count <= MAX_COUNT:
        logger.error('--count must be between 1 and %d.', MAX_COUNT)
        return 2
    try:
        build_card_fields(args.credits, '')
    except ValueError as err:
        logger.error('%s', err)
        return 2

    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    sm = SecretsManager()
    await sm.initialize()
    cache_service = CacheService()
    directus = DirectusService(cache_service=cache_service,
                               encryption_service=EncryptionService(cache_service=cache_service))
    try:
        if not await schema_has_marks_test_account(directus):
            logger.error('gift_cards.marks_test_account is missing; deploy the schema first.')
            return 1
        if args.count_remaining:
            print(await count_remaining(directus))
            return 0
        if args.dry_run:
            logger.info('Dry run: would create %d cards of %d credits.', args.count, args.credits)
            return 0
        codes = await create_batch(directus, args.count, args.credits,
                                   f'ai-test-users batch {date.today().isoformat()}')
        print('\n'.join(codes))
        return 0
    except RuntimeError as err:
        logger.error('%s', err)
        return 1
    finally:
        await sm.aclose()
        await directus.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(levelname)s %(message)s')
    sys.exit(asyncio.run(main()))
