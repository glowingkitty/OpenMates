#!/usr/bin/env python3
"""
One-time migration script: populate the slug field for all existing demo chats.

Generates slugs from the English title of each demo chat and writes them to Directus.
Run this once after adding the slug field to demo_chats.

Usage:
    docker exec api python /app/backend/scripts/migrate_demo_slugs.py
    docker exec api python /app/backend/scripts/migrate_demo_slugs.py --dry-run
"""

import asyncio
import argparse
import logging
import re
import sys

sys.path.insert(0, '/app')

from backend.core.api.app.services.directus.directus import DirectusService

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('migrate_demo_slugs')
logger.setLevel(logging.INFO)


def slugify(text: str) -> str:
    """Convert a title to a URL-safe slug with 'demo-' prefix."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return f'demo-{text.strip("-")}'


async def main(dry_run: bool = False) -> None:
    svc = DirectusService()

    # Get all demo chats
    all_items = await svc.get_items('demo_chats', {
        'fields': ['id', 'slug'],
        'limit': 500
    })
    logger.info(f'Total demo chats: {len(all_items)}')

    # Filter ones with no slug
    to_migrate = [item for item in all_items if not item.get('slug')]
    logger.info(f'Need slug: {len(to_migrate)}')

    if not to_migrate:
        print('All demo chats already have slugs — nothing to do.')
        return

    # For each, fetch English translation to get the English title
    updated = 0
    for item in to_migrate:
        uuid = item['id']

        # Get English translation
        translations = await svc.get_items('demo_chat_translations', {
            'filter': {
                'demo_chat_id': {'_eq': uuid},
                'language_code': {'_eq': 'en'}
            },
            'fields': ['title'],
            'limit': 1
        })

        if not translations:
            # No English translation — fall back to UUID prefix
            slug = f'demo-{uuid[:8]}'
            logger.warning(f'No English translation for {uuid}, using UUID slug: {slug}')
        else:
            title = translations[0].get('title') or ''
            slug = slugify(title) if title else f'demo-{uuid[:8]}'

        print(f"  {'[DRY RUN] ' if dry_run else ''}Set {uuid[:8]}... -> {slug!r}")

        if not dry_run:
            result = await svc.update_item('demo_chats', uuid, {'slug': slug})
            if result:
                updated += 1
            else:
                logger.error(f'Failed to update slug for {uuid}')

    if dry_run:
        print(f'\nDry run complete — would have updated {len(to_migrate)} records')
    else:
        print(f'\nDone: {updated}/{len(to_migrate)} slugs written successfully')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate demo chat slugs')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without writing')
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
