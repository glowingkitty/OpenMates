#!/usr/bin/env python3
"""
Script to backfill historical server-wide statistics into Directus global stats models.
Optimized for high-volume environments (millions of messages/usage entries).

This script properly calculates:
- credits_used: From actual usage entries (encrypted_credits_costs_total decrypted and summed)
- new_users_registered: From directus_activity log (user creation events)
- new_users_finished_signup: From invoices (first purchase indicates signup completion)
- messages_sent: From messages collection
- chats_created: From chats collection
- embeds_created: From embeds collection
- income/credits_sold: From invoices
"""

import asyncio
import logging
import sys
import hashlib
from datetime import datetime, date
from collections import defaultdict
from typing import Dict, Any, Optional, Set

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('backfill_stats')

# Optimized constants for scale
BATCH_SIZE_LARGE = 1000  # For simple metadata scans
BATCH_SIZE_DECRYPT = 200  # For encryption-heavy tasks
CONCURRENCY_LIMIT = 50


async def backfill():
    """
    Main backfill function that collects historical data and persists it to Directus.
    
    Data sources:
    1. User registrations: directus_activity log (action='create', collection='directus_users')
    2. Credits used: usage entries (decrypt encrypted_credits_costs_total and aggregate by day)
    3. Messages/Chats/Embeds: count by created_at timestamp
    4. Income/Credits sold: invoices (decrypt amounts)
    5. Finished signups: first invoice per user (indicates completed signup)
    """
    sm = SecretsManager()
    await sm.initialize()
    
    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    
    try:
        logger.info("=" * 60)
        logger.info("Starting production-grade stats backfill...")
        logger.info("=" * 60)
        
        # ============================================================================
        # STEP 1: Establish User Map (user_id -> vault_key_id) and Current Liability
        # ============================================================================
        logger.info("\n[STEP 1] Building user map and calculating current liability...")
        
        user_map: Dict[str, str] = {}  # user_id -> vault_key_id
        user_hash_map: Dict[str, str] = {}  # user_id_hash -> vault_key_id
        total_liability = 0
        total_users_count = 0
        admin_user_ids: Set[str] = set()
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

        async def decrypt_balance(encrypted_val: str, vault_key_id: str) -> int:
            """Decrypt a user's credit balance."""
            async with semaphore:
                try:
                    result = await encryption_service.decrypt_with_user_key(encrypted_val, vault_key_id)
                    return int(result) if result and result.isdigit() else 0
                except Exception:
                    return 0

        offset = 0
        while True:
            users = await directus_service.get_items('directus_users', params={
                'fields': 'id,vault_key_id,encrypted_credit_balance,is_admin',
                'limit': BATCH_SIZE_DECRYPT,
                'offset': offset
            })
            if not users:
                break
            
            tasks = []
            for user in users:
                user_id = user.get('id')
                is_admin = user.get('is_admin', False)
                vault_key_id = user.get('vault_key_id')
                
                if is_admin:
                    admin_user_ids.add(user_id)
                    continue
                    
                total_users_count += 1
                
                if user_id and vault_key_id:
                    user_map[user_id] = vault_key_id
                    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
                    user_hash_map[user_hash] = vault_key_id
                    
                    if user.get('encrypted_credit_balance'):
                        tasks.append(decrypt_balance(user['encrypted_credit_balance'], vault_key_id))
            
            if tasks:
                results = await asyncio.gather(*tasks)
                total_liability += sum(results)
            
            offset += BATCH_SIZE_DECRYPT
            if offset % 1000 == 0:
                logger.info(f"  Processed {offset} users...")

        logger.info(f"  Total non-admin users: {total_users_count}")
        logger.info(f"  Current liability: {total_liability} credits")
        
        # Update cache with current liability
        await cache_service.set_total_liability(total_liability)

        # ============================================================================
        # STEP 2: Initialize aggregation structure
        # ============================================================================
        daily_records: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "new_users_registered": 0,
            "new_users_finished_signup": 0,
            "income_eur_cents": 0,
            "credits_sold": 0,
            "credits_used": 0,
            "messages_sent": 0,
            "chats_created": 0,
            "embeds_created": 0,
            "liability_total": 0,
            "active_subscriptions": 0,
            "total_regular_users": 0
        })

        # ============================================================================
        # STEP 3: Get user registrations from directus_activity log
        # ============================================================================
        logger.info("\n[STEP 3] Processing user registrations from activity log...")
        
        offset = 0
        registrations_count = 0
        while True:
            activities = await directus_service.get_items('directus_activity', params={
                'fields': 'item,timestamp',
                'filter': {
                    '_and': [
                        {'action': {'_eq': 'create'}},
                        {'collection': {'_eq': 'directus_users'}}
                    ]
                },
                'limit': BATCH_SIZE_LARGE,
                'offset': offset,
                'sort': 'timestamp'
            })
            
            if not activities:
                break
                
            for activity in activities:
                user_id = activity.get('item')
                timestamp_str = activity.get('timestamp')
                
                # Skip admin users
                if user_id in admin_user_ids:
                    continue
                
                if timestamp_str:
                    try:
                        # Parse ISO timestamp (e.g., '2026-01-21T10:47:24.511Z')
                        if 'T' in timestamp_str:
                            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                            date_str = dt.strftime('%Y-%m-%d')
                        else:
                            date_str = timestamp_str[:10]
                        
                        # Skip invalid dates (before 2020, likely Unix epoch or invalid data)
                        year = int(date_str[:4])
                        if year < 2020:
                            logger.warning(f"  Skipping invalid registration date: {date_str} (year: {year})")
                            continue
                        
                        daily_records[date_str]["new_users_registered"] += 1
                        registrations_count += 1
                    except Exception as e:
                        logger.warning(f"  Failed to parse timestamp {timestamp_str}: {e}")
            
            offset += BATCH_SIZE_LARGE
            if offset % 5000 == 0:
                logger.info(f"  Processed {offset} activity entries...")

        logger.info(f"  Total user registrations found: {registrations_count}")

        # ============================================================================
        # STEP 4: Process usage entries for credits_used
        # ============================================================================
        logger.info("\n[STEP 4] Processing usage entries for credits_used...")
        
        # First, get total count
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f'{directus_service.base_url}/items/usage',
                params={'limit': 1, 'meta': 'total_count'},
                headers={'Authorization': f'Bearer {admin_token}'}
            )
            total_usage = 0
            if resp.status_code == 200:
                total_usage = resp.json().get('meta', {}).get('total_count', 0)
        
        logger.info(f"  Total usage entries to process: {total_usage}")
        
        async def decrypt_credits(entry: Dict[str, Any]) -> Optional[tuple]:
            """Decrypt credits from a usage entry and return (date_str, credits)."""
            encrypted_credits = entry.get('encrypted_credits_costs_total')
            user_hash = entry.get('user_id_hash')
            created_at = entry.get('created_at')
            
            if not encrypted_credits or not user_hash or not created_at:
                return None
                
            vault_key_id = user_hash_map.get(user_hash)
            if not vault_key_id:
                return None
            
            async with semaphore:
                try:
                    decrypted = await encryption_service.decrypt_with_user_key(encrypted_credits, vault_key_id)
                    credits = int(decrypted) if decrypted and decrypted.isdigit() else 0
                    
                    # Convert Unix timestamp to date string
                    if isinstance(created_at, int):
                        # Skip invalid timestamps (before 2020, likely Unix epoch or invalid)
                        if created_at < 1577836800:  # 2020-01-01 00:00:00 UTC
                            return None
                        date_str = datetime.fromtimestamp(created_at).strftime('%Y-%m-%d')
                    else:
                        date_str = str(created_at)[:10]
                    
                    # Double-check year is valid
                    year = int(date_str[:4])
                    if year < 2020:
                        return None
                    
                    return (date_str, credits)
                except Exception:
                    return None

        offset = 0
        total_credits_used = 0
        while True:
            usage_entries = await directus_service.get_items('usage', params={
                'fields': 'user_id_hash,created_at,encrypted_credits_costs_total',
                'limit': BATCH_SIZE_DECRYPT,
                'offset': offset
            })
            
            if not usage_entries:
                break
            
            tasks = [decrypt_credits(entry) for entry in usage_entries]
            results = await asyncio.gather(*tasks)
            
            for result in results:
                if result:
                    date_str, credits = result
                    daily_records[date_str]["credits_used"] += credits
                    total_credits_used += credits
            
            offset += BATCH_SIZE_DECRYPT
            if offset % 1000 == 0:
                logger.info(f"  Processed {offset}/{total_usage} usage entries...")

        logger.info(f"  Total credits used: {total_credits_used}")

        # ============================================================================
        # STEP 5: Process messages, chats, and embeds
        # ============================================================================
        logger.info("\n[STEP 5] Processing engagement data (messages, chats, embeds)...")
        
        for collection, field in [('messages', 'messages_sent'), ('chats', 'chats_created'), ('embeds', 'embeds_created')]:
            logger.info(f"  Processing {collection}...")
            offset = 0
            count = 0
            
            while True:
                items = await directus_service.get_items(collection, params={
                    'fields': 'created_at',
                    'limit': BATCH_SIZE_LARGE,
                    'offset': offset
                })
                
                if not items:
                    break
                    
                for item in items:
                    created_at = item.get('created_at')
                    if created_at:
                        try:
                            # Handle Unix timestamps
                            if isinstance(created_at, int):
                                # Skip invalid timestamps (before 2020)
                                if created_at < 1577836800:  # 2020-01-01 00:00:00 UTC
                                    continue
                                date_str = datetime.fromtimestamp(created_at).strftime('%Y-%m-%d')
                            else:
                                date_str = str(created_at)[:10]
                            
                            # Double-check year is valid
                            year = int(date_str[:4])
                            if year < 2020:
                                continue
                            
                            daily_records[date_str][field] += 1
                            count += 1
                        except Exception:
                            pass
                
                offset += BATCH_SIZE_LARGE
            
            logger.info(f"    {collection}: {count} entries")

        # ============================================================================
        # STEP 6: Process invoices (income, credits sold, finished signups)
        # ============================================================================
        logger.info("\n[STEP 6] Processing invoices (income, credits sold, finished signups)...")
        
        finished_signup_users: Set[str] = set()  # Track which users have their first invoice counted

        async def process_invoice(invoice: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Process an invoice and return aggregated data."""
            user_hash = invoice.get('user_id_hash')
            vault_key_id = user_hash_map.get(user_hash)
            
            if not vault_key_id:
                return None
            
            invoice_date = invoice.get('date')
            if not invoice_date:
                return None
            
            async with semaphore:
                try:
                    # Decrypt amount and credits
                    encrypted_amount = invoice.get('encrypted_amount')
                    encrypted_credits = invoice.get('encrypted_credits_purchased')
                    
                    amount = 0
                    credits = 0
                    
                    if encrypted_amount:
                        amt_str = await encryption_service.decrypt_with_user_key(encrypted_amount, vault_key_id)
                        amount = int(amt_str) if amt_str and amt_str.isdigit() else 0
                    
                    if encrypted_credits:
                        cred_str = await encryption_service.decrypt_with_user_key(encrypted_credits, vault_key_id)
                        credits = int(cred_str) if cred_str and cred_str.isdigit() else 0
                    
                    date_str = invoice_date[:10]
                    # Skip invalid dates (before 2020)
                    year = int(date_str[:4])
                    if year < 2020:
                        return None
                    
                    return {
                        "date": date_str,
                        "amount": amount,
                        "credits": credits,
                        "user_hash": user_hash
                    }
                except Exception:
                    return None

        offset = 0
        total_income = 0
        total_credits_sold = 0
        while True:
            invoices = await directus_service.get_items('invoices', params={
                'fields': 'user_id_hash,date,encrypted_amount,encrypted_credits_purchased,refund_status',
                'limit': BATCH_SIZE_DECRYPT,
                'offset': offset
            })
            
            if not invoices:
                break
            
            # Only process non-refunded invoices
            valid_invoices = [inv for inv in invoices if inv.get('refund_status') != 'completed']
            tasks = [process_invoice(inv) for inv in valid_invoices]
            results = await asyncio.gather(*tasks)
            
            for result in results:
                if result:
                    date_str = result['date']
                    daily_records[date_str]["income_eur_cents"] += result['amount']
                    daily_records[date_str]["credits_sold"] += result['credits']
                    total_income += result['amount']
                    total_credits_sold += result['credits']
                    
                    # Track first invoice as finished signup
                    if result['user_hash'] not in finished_signup_users:
                        finished_signup_users.add(result['user_hash'])
                        daily_records[date_str]["new_users_finished_signup"] += 1
            
            offset += BATCH_SIZE_DECRYPT
            if offset % 500 == 0:
                logger.info(f"  Processed {offset} invoices...")

        logger.info(f"  Total income: {total_income / 100:.2f} EUR")
        logger.info(f"  Total credits sold: {total_credits_sold}")
        logger.info(f"  Finished signups: {len(finished_signup_users)}")

        # ============================================================================
        # STEP 7: Persist daily records to Directus
        # ============================================================================
        logger.info("\n[STEP 7] Persisting aggregated results to Directus...")
        
        sorted_dates = sorted(daily_records.keys())
        today_str = date.today().isoformat()
        
        for date_str in sorted_dates:
            # Skip invalid dates (before 2020)
            year = int(date_str[:4])
            if year < 2020:
                logger.warning(f"  Skipping invalid date record: {date_str}")
                continue
            
            record = daily_records[date_str]
            record["date"] = date_str
            
            # For today's record, include current snapshot values
            if date_str == today_str:
                record["liability_total"] = total_liability
                record["total_regular_users"] = total_users_count
            
            try:
                existing = await directus_service.analytics.get_server_stats_daily(date_str)
                if existing:
                    await directus_service.analytics.update_server_stats_daily(existing["id"], record)
                else:
                    await directus_service.analytics.create_server_stats_daily(record)
            except Exception as e:
                logger.error(f"  Failed to persist record for {date_str}: {e}")

        logger.info(f"  Persisted {len(sorted_dates)} daily records")

        # ============================================================================
        # STEP 8: Update monthly aggregations
        # ============================================================================
        logger.info("\n[STEP 8] Aggregating monthly data...")
        
        months = sorted(list(set(d[:7] for d in sorted_dates if int(d[:4]) >= 2020)))
        
        from backend.core.api.app.tasks.server_stats_tasks import update_monthly_stats
        
        class MockTask:
            """Mock task object for reusing the monthly stats update function."""
            def __init__(self, ds, cs):
                self.directus_service = ds
                self.cache_service = cs
            async def cleanup_services(self):
                pass
            async def initialize_services(self):
                pass
        
        mock_task = MockTask(directus_service, cache_service)
        
        for month in months:
            try:
                await update_monthly_stats(mock_task, month)
            except Exception as e:
                logger.error(f"  Failed to update monthly stats for {month}: {e}")

        logger.info(f"  Updated {len(months)} monthly records")

        # ============================================================================
        # SUMMARY
        # ============================================================================
        logger.info("\n" + "=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  Days processed: {len(sorted_dates)}")
        logger.info(f"  Months processed: {len(months)}")
        logger.info(f"  Total users registered: {registrations_count}")
        logger.info(f"  Total finished signups: {len(finished_signup_users)}")
        logger.info(f"  Total credits used: {total_credits_used}")
        logger.info(f"  Total income: €{total_income / 100:.2f}")
        logger.info(f"  Total credits sold: {total_credits_sold}")
        logger.info(f"  Current liability: {total_liability} credits")

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
    finally:
        await sm.aclose()
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(backfill())
