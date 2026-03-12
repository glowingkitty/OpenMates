#!/usr/bin/env python3
"""Fix demo chat slugs to be title-based instead of UUID-based."""
import asyncio, sys, re
sys.path.insert(0, '/app')
from backend.core.api.app.services.directus.directus import DirectusService

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return f'demo-{text.strip("-")}'

async def main():
    svc = DirectusService()
    items = await svc.get_items('demo_chats', {'fields': ['id', 'title', 'slug'], 'limit': 200})
    print(f'Total: {len(items)}')
    for item in items:
        uuid = item['id']
        title = item.get('title') or ''
        current_slug = item.get('slug') or ''
        new_slug = slugify(title) if title else None
        print(f'  {uuid[:8]} current={current_slug!r} -> new={new_slug!r}')
        if new_slug and new_slug != current_slug:
            result = await svc.update_item('demo_chats', uuid, {'slug': new_slug})
            print(f'    {"OK" if result else "FAILED"}')
        elif new_slug == current_slug:
            print(f'    already correct')

asyncio.run(main())
