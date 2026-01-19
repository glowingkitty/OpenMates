#!/usr/bin/env python3
"""
Script to display server-wide statistics including user signups, financial metrics,
and credit usage over time.

Optimized version for large-scale production environments.

Usage:
    docker exec api python /app/backend/scripts/server_stats.py

Options:
    --weeks N           Number of weeks to show (default: 4)
    --months N          Number of months to show (default: 6)
    --json              Output as JSON instead of formatted text
"""

import asyncio
import argparse
import hashlib
import logging
import sys
import json
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService, CREATOR_INCOME_ENCRYPTION_KEY
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('server_stats')
logger.setLevel(logging.INFO)

# Suppress verbose logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)

# Constants for scaling
BATCH_SIZE = 500
CONCURRENCY_LIMIT = 50  # Limit parallel decryption tasks

async def get_count(directus_service: DirectusService, collection: str, filter_dict: Optional[Dict] = None, admin_required: bool = True) -> int:
    """Helper to get count of items in a collection with optional filtering."""
    try:
        url = f"{directus_service.base_url}"
        if collection == 'users':
            url += "/users"
        else:
            url += f"/items/{collection}"
            
        params = {
            'limit': 1,
            'meta': 'filter_count'
        }
        if filter_dict:
            params['filter'] = json.dumps(filter_dict)
            
        admin_token = await directus_service.ensure_auth_token(admin_required=admin_required)
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        resp = await directus_service._make_api_request("GET", url, params=params, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('meta', {}).get('filter_count', 0)
        return 0
    except Exception as e:
        logger.error(f"Error getting count for {collection}: {e}")
        return 0

async def fetch_in_batches(directus_service: DirectusService, collection: str, params: Dict[str, Any], admin_required: bool = True):
    """Generator to fetch items in batches to avoid memory issues."""
    offset = 0
    while True:
        batch_params = params.copy()
        batch_params['limit'] = BATCH_SIZE
        batch_params['offset'] = offset
        
        items = await directus_service.get_items(collection, params=batch_params, admin_required=admin_required)
        if not items:
            break
            
        for item in items:
            yield item
            
        if len(items) < BATCH_SIZE:
            break
        offset += BATCH_SIZE

async def get_signup_stats(directus_service: DirectusService) -> Dict[str, Any]:
    """Get statistics about user signups and subscriptions using optimized queries."""
    stats = {
        'total_users': 0,
        'finished_signup': 0,
        'in_signup_flow': 0,
        'just_registered': 0,
        'subscriptions_active': 0,
        'auto_topup_enabled': 0
    }
    
    # 1. Basic counts using optimized meta queries
    stats['total_users'] = await get_count(directus_service, 'users', {'is_admin': {'_eq': False}})
    stats['subscriptions_active'] = await get_count(directus_service, 'users', {
        '_and': [
            {'is_admin': {'_eq': False}},
            {'stripe_subscription_id': {'_nnull': True}},
            {'subscription_status': {'_eq': 'active'}}
        ]
    })
    stats['auto_topup_enabled'] = await get_count(directus_service, 'users', {
        '_and': [
            {'is_admin': {'_eq': False}},
            {'auto_topup_low_balance_enabled': {'_eq': True}}
        ]
    })
    stats['just_registered'] = await get_count(directus_service, 'users', {
        '_and': [
            {'is_admin': {'_eq': False}},
            {'last_opened': {'_null': True}}
        ]
    })
    stats['in_signup_flow'] = await get_count(directus_service, 'users', {
        '_and': [
            {'is_admin': {'_eq': False}},
            {'last_opened': {'_starts_with': '/signup/'}}
        ]
    })

    # 2. Finished Signup (users with invoices or gift cards)
    # Note: This is an approximation because there might be overlap.
    # We fetch all hashes but only for those who paid, which should be fewer than total users.
    try:
        paid_hashes: Set[str] = set()
        async for inv in fetch_in_batches(directus_service, 'invoices', {'fields': 'user_id_hash'}):
            h = inv.get('user_id_hash')
            if h:
                paid_hashes.add(h)
            
        async for gc in fetch_in_batches(directus_service, 'redeemed_gift_cards', {'fields': 'user_id_hash'}):
            h = gc.get('user_id_hash')
            if h:
                paid_hashes.add(h)
            
        stats['finished_signup'] = len(paid_hashes)
    except Exception as e:
        logger.error(f"Error calculating finished signup stats: {e}")

    return stats

async def get_financial_stats(
    directus_service: DirectusService, 
    encryption_service: EncryptionService,
    hash_to_vault_key: Dict[str, str],
    user_balances: List[Tuple[str, str]],
    weeks: int = 4,
    months: int = 6,
    finished_signup_count: int = 0
) -> Dict[str, Any]:
    """Get financial statistics with chunked processing and concurrency limits."""
    
    today = date.today()
    week_cutoff = today - timedelta(weeks=weeks)
    month_cutoff = today - timedelta(days=months * 30)
    cutoff = min(week_cutoff, month_cutoff)
    
    stats = {
        "weekly": defaultdict(lambda: {"income": 0, "credits": 0}),
        "monthly": defaultdict(lambda: {"income": 0, "credits": 0}),
        "total_income": 0,
        "total_credits": 0,
        "liability_credits": 0,
        "arpu": 0
    }

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def decrypt_safe(val, v_id):
        async with semaphore:
            return await encryption_service.decrypt_with_user_key(val, v_id)

    try:
        # 1. Outstanding Liability (chunked)
        total_outstanding = 0
        for i in range(0, len(user_balances), BATCH_SIZE):
            chunk = user_balances[i:i + BATCH_SIZE]
            tasks = [decrypt_safe(bal, v_id) for bal, v_id in chunk]
            results = await asyncio.gather(*tasks)
            total_outstanding += sum(int(r) for r in results if r and r.isdigit())
        stats["liability_credits"] = total_outstanding

        # 2. Fetch and Decrypt Invoices (chunked)
        params_inv = {
            'filter': json.dumps({'date': {'_gte': cutoff.isoformat()}}),
            'fields': 'id,user_id_hash,date,encrypted_amount,encrypted_credits_purchased,is_gift_card,refund_status'
        }
        
        invoices_to_process = []
        async for inv in fetch_in_batches(directus_service, 'invoices', params_inv):
            u_hash = inv.get('user_id_hash')
            v_key_id = hash_to_vault_key.get(u_hash)
            if v_key_id:
                invoices_to_process.append((inv, v_key_id))
        
        # Process invoice decryptions in chunks
        for i in range(0, len(invoices_to_process), BATCH_SIZE):
            chunk = invoices_to_process[i:i + BATCH_SIZE]
            tasks = []
            for inv, v_id in chunk:
                tasks.append(process_invoice(inv, v_id, encryption_service, semaphore))
            
            decrypted_results = await asyncio.gather(*tasks)
            for inv in decrypted_results:
                if not inv or inv.get('refund_status') == 'completed':
                    continue
                
                d = inv['date']
                week_id = d.strftime("%Y-W%W")
                month_id = d.strftime("%Y-%m")
                amount = inv['amount']
                credits_purchased = inv['credits']
                
                stats["weekly"][week_id]["income"] += amount / 100.0
                stats["weekly"][week_id]["credits"] += credits_purchased
                stats["monthly"][month_id]["income"] += amount / 100.0
                stats["monthly"][month_id]["credits"] += credits_purchased
                stats["total_income"] += amount / 100.0
                stats["total_credits"] += credits_purchased
                
        if finished_signup_count > 0:
            stats["arpu"] = stats["total_income"] / finished_signup_count
            
    except Exception as e:
        logger.error(f"Error fetching financial stats: {e}", exc_info=True)
        
    return stats

async def process_invoice(inv: Dict[str, Any], vault_key_id: str, encryption_service: EncryptionService, semaphore: asyncio.Semaphore) -> Optional[Dict[str, Any]]:
    """Decrypt and process a single invoice with semaphore."""
    try:
        async with semaphore:
            amount_str = await encryption_service.decrypt_with_user_key(inv['encrypted_amount'], vault_key_id)
            credits_str = await encryption_service.decrypt_with_user_key(inv['encrypted_credits_purchased'], vault_key_id)
        
        if amount_str is None or credits_str is None:
            return None
            
        date_val = inv.get('date')
        if isinstance(date_val, str):
            dt = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        else:
            dt = date_val
            
        return {
            "amount": float(amount_str),
            "credits": int(credits_str),
            "date": dt,
            "refund_status": inv.get('refund_status')
        }
    except Exception:
        return None

async def get_usage_stats(
    directus_service: DirectusService, 
    encryption_service: EncryptionService,
    hash_to_vault_key: Dict[str, str],
    months: int = 6
) -> Dict[str, Any]:
    """Get usage statistics using summaries and chunked raw usage for current month."""
    stats = {
        "monthly": defaultdict(lambda: {"credits": 0, "requests": 0}),
        "skill_breakdown": defaultdict(lambda: {"credits": 0, "requests": 0}),
        "total_used": 0,
        "total_requests": 0
    }
    
    today = date.today()
    month_start = datetime(today.year, today.month, 1)
    month_start_ts = int(month_start.timestamp())
    
    # 1. Fetch Monthly Summaries (historical)
    try:
        # We'll fetch all summaries as they are already aggregated and relatively few
        summaries = await directus_service.get_items('usage_monthly_app_summaries', params={'limit': -1}, admin_required=True)
        for s in summaries:
            ym = s.get('year_month')
            credits = s.get('total_credits', 0)
            requests = s.get('entry_count', 0)
            stats["monthly"][ym]["credits"] += credits
            stats["monthly"][ym]["requests"] += requests
            stats["total_used"] += credits
            stats["total_requests"] += requests

        # 2. Current Month Skill Breakdown (chunked)
        params_raw = {
            'filter': json.dumps({'created_at': {'_gte': month_start_ts}}),
            'fields': 'user_id_hash,app_id,skill_id,encrypted_credits_costs_total'
        }
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        
        raw_entries = []
        async for entry in fetch_in_batches(directus_service, 'usage', params_raw):
            raw_entries.append(entry)
            
            # Process in chunks to avoid building a massive list of tasks
            if len(raw_entries) >= BATCH_SIZE:
                await process_usage_chunk(raw_entries, hash_to_vault_key, encryption_service, semaphore, stats)
                raw_entries = []
        
        if raw_entries:
            await process_usage_chunk(raw_entries, hash_to_vault_key, encryption_service, semaphore, stats)
                
    except Exception as e:
        logger.error(f"Error fetching usage stats: {e}", exc_info=True)
        
    return stats

async def process_usage_chunk(entries, hash_to_vault_key, encryption_service, semaphore, stats):
    """Process a chunk of usage entries."""
    tasks = []
    for entry in entries:
        u_hash = entry.get('user_id_hash')
        v_key_id = hash_to_vault_key.get(u_hash)
        enc_credits = entry.get('encrypted_credits_costs_total')
        
        if v_key_id and enc_credits:
            async def d(enc, v_id):
                async with semaphore:
                    return await encryption_service.decrypt_with_user_key(enc, v_id)
            tasks.append(d(enc_credits, v_key_id))
        else:
            tasks.append(asyncio.sleep(0, result="0"))
            
    results = await asyncio.gather(*tasks)
    for entry, credit_val in zip(entries, results):
        app = entry.get('app_id', 'unknown')
        skill = entry.get('skill_id', 'unknown')
        skill_key = f"{app}.{skill}"
        credits = int(credit_val) if credit_val and credit_val.isdigit() else 0
        stats["skill_breakdown"][skill_key]["credits"] += credits
        stats["skill_breakdown"][skill_key]["requests"] += 1

async def get_creator_stats(directus_service: DirectusService, encryption_service: EncryptionService) -> Dict[str, Any]:
    """Get creator stats with chunked decryption."""
    stats = {"reserved_credits": 0, "claimed_credits": 0, "total_entries": 0}
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    try:
        entries = []
        async for e in fetch_in_batches(directus_service, 'creator_income', {'fields': 'status,encrypted_credits_reserved'}):
            entries.append(e)
            
            if len(entries) >= BATCH_SIZE:
                await process_creator_chunk(entries, encryption_service, semaphore, stats)
                entries = []
        
        if entries:
            await process_creator_chunk(entries, encryption_service, semaphore, stats)
            
    except Exception as e:
        logger.error(f"Error fetching creator stats: {e}")
        
    return stats

async def process_creator_chunk(entries, encryption_service, semaphore, stats):
    stats["total_entries"] += len(entries)
    tasks = []
    for e in entries:
        enc = e.get('encrypted_credits_reserved')
        if enc:
            async def d(v):
                async with semaphore:
                    return await encryption_service.decrypt(v, key_name=CREATOR_INCOME_ENCRYPTION_KEY)
            tasks.append(d(enc))
        else:
            tasks.append(asyncio.sleep(0, result=None))
            
    results = await asyncio.gather(*tasks)
    for e, res in zip(entries, results):
        if res and res.isdigit():
            val = int(res)
            if e.get('status') == 'reserved':
                stats["reserved_credits"] += val
            elif e.get('status') == 'claimed':
                stats["claimed_credits"] += val

async def get_engagement_stats(directus_service: DirectusService, months: int = 6) -> Dict[str, Any]:
    """Get engagement stats using optimized count queries for each month."""
    stats = {
        "monthly": defaultdict(lambda: {"chats": 0, "messages": 0, "embeds": 0}),
        "total_chats": 0, "total_messages": 0, "total_embeds": 0
    }
    
    # 1. Totals
    for coll in ['chats', 'messages', 'embeds']:
        stats[f"total_{coll}"] = await get_count(directus_service, coll)

    # 2. Monthly breakdown (one query per month/collection)
    today = date.today()
    for i in range(months):
        m_start = (today.replace(day=1) - timedelta(days=i*31)).replace(day=1)
        m_next = (m_start + timedelta(days=32)).replace(day=1)
        
        ts_start = int(datetime.combine(m_start, datetime.min.time()).timestamp())
        ts_end = int(datetime.combine(m_next, datetime.min.time()).timestamp())
        
        month_id = m_start.strftime("%Y-%m")
        filter_dict = {'_and': [{'created_at': {'_gte': ts_start}}, {'created_at': {'_lt': ts_end}}]}
        
        # We can run these in parallel for the month
        c_task = get_count(directus_service, 'chats', filter_dict)
        m_task = get_count(directus_service, 'messages', filter_dict)
        e_task = get_count(directus_service, 'embeds', filter_dict)
        
        c, m, e = await asyncio.gather(c_task, m_task, e_task)
        stats["monthly"][month_id] = {"chats": c, "messages": m, "embeds": e}
        
    return stats

def format_output(signup_stats, financial_stats, usage_stats, engagement_stats, creator_stats, weeks, months) -> str:
    """Format the report (same as before but more robust)."""
    # Reuse the same formatting logic from the original script
    # (Copied from previous read_file output for consistency)
    lines = []
    lines.append("=" * 100)
    lines.append("SERVER STATISTICS REPORT (SCALABLE)")
    lines.append("=" * 100)
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)
    
    lines.append("-" * 100)
    lines.append("USER GROWTH & ENGAGEMENT")
    lines.append("-" * 100)
    lines.append(f"  Total Regular Users:   {signup_stats.get('total_users', 0):>10,}")
    lines.append(f"  Finished Signup*:      {signup_stats.get('finished_signup', 0):>10,}")
    lines.append(f"  In Signup Flow:        {signup_stats.get('in_signup_flow', 0):>10,}")
    lines.append(f"  Just Registered:       {signup_stats.get('just_registered', 0):>10,}")
    lines.append("")
    lines.append(f"  Total Chats:           {engagement_stats.get('total_chats', 0):>10,}")
    lines.append(f"  Total Messages:        {engagement_stats.get('total_messages', 0):>10,}")
    lines.append(f"  Total Embeds:          {engagement_stats.get('total_embeds', 0):>10,}")
    lines.append("")
    lines.append(f"  Active Subscriptions:  {signup_stats.get('subscriptions_active', 0):>10,}")
    lines.append(f"  Auto Top-up Enabled:   {signup_stats.get('auto_topup_enabled', 0):>10,}")
    lines.append("")
    
    lines.append("-" * 100)
    lines.append("FINANCIAL OVERVIEW")
    lines.append("-" * 100)
    lines.append(f"  Total Income (L6M):    {financial_stats.get('total_income', 0):>10.2f} EUR")
    lines.append(f"  ARPU (Lifetime)*:      {financial_stats.get('arpu', 0):>10.2f} EUR")
    lines.append("")
    lines.append(f"  User Credit Balance (Liability): {financial_stats.get('liability_credits', 0):>10,} Credits")
    lines.append(f"  Creator Reserved Credits:        {creator_stats.get('reserved_credits', 0):>10,} Credits")
    lines.append("")
    
    lines.append("-" * 100)
    lines.append("USAGE BY SKILL (Current Month)")
    lines.append("-" * 100)
    lines.append(f"  {'Skill':<25} | {'Credits Used':>15} | {'Requests':>12}")
    lines.append("-" * 100)
    if not usage_stats["skill_breakdown"]:
        lines.append("  No usage recorded this month.")
    else:
        for skill, data in sorted(usage_stats["skill_breakdown"].items(), key=lambda x: x[1]['credits'], reverse=True):
            lines.append(f"  {skill:<25} | {data['credits']:>15,} | {data['requests']:>12,}")
    lines.append("")
    
    lines.append("-" * 100)
    lines.append(f"MONTHLY DEVELOPMENT (Last {months} Months)")
    lines.append("-" * 100)
    lines.append(f"  {'Month':<10} | {'Income':>10} | {'Cred.Sold':>10} | {'Cred.Used':>10} | {'Chats':>8} | {'Msgs':>10} | {'Embeds':>8}")
    lines.append("-" * 100)
    
    all_months = sorted(list(
        set(financial_stats["monthly"].keys()) | 
        set(usage_stats["monthly"].keys()) | 
        set(engagement_stats["monthly"].keys())
    ), reverse=True)[:months]
    
    for month in all_months:
        f_stat = financial_stats["monthly"].get(month, {"income": 0, "credits": 0})
        u_stat = usage_stats["monthly"].get(month, {"credits": 0, "requests": 0})
        e_stat = engagement_stats["monthly"].get(month, {"chats": 0, "messages": 0, "embeds": 0})
        lines.append(
            f"  {month:<10} | {f_stat['income']:>10.2f} | {f_stat['credits']:>10,} | {u_stat['credits']:>10,} | "
            f"{e_stat['chats']:>8,} | {e_stat['messages']:>10,} | {e_stat['embeds']:>8,}"
        )
    
    lines.append("\n" + "=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    return "\n".join(lines)

async def main():
    parser = argparse.ArgumentParser(description='Server-wide statistics (Scalable)')
    parser.add_argument('--weeks', type=int, default=4, help='Number of weeks to show')
    parser.add_argument('--months', type=int, default=6, help='Number of months to show')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()
    
    sm = SecretsManager()
    await sm.initialize()
    
    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    
    try:
        # 1. Signup stats (Optimized)
        signup_stats = await get_signup_stats(directus_service)
        
        # 2. Get User Map (Chunked)
        hash_to_vault_key = {}
        user_balances = []
        async for u in fetch_in_batches(directus_service, 'users', {'fields': 'id,vault_key_id,encrypted_credit_balance', 'filter': json.dumps({'is_admin': {'_eq': False}})}):
            u_id = u.get('id')
            v_key_id = u.get('vault_key_id')
            if u_id:
                u_hash = hashlib.sha256(u_id.encode()).hexdigest()
                hash_to_vault_key[u_hash] = v_key_id
                if v_key_id and u.get('encrypted_credit_balance'):
                    user_balances.append((u.get('encrypted_credit_balance'), v_key_id))

        # 3. Financial stats (Optimized & Chunked)
        financial_stats = await get_financial_stats(
            directus_service, encryption_service, hash_to_vault_key, user_balances,
            weeks=args.weeks, months=args.months, finished_signup_count=signup_stats.get('finished_signup', 0)
        )
        
        # 4. Usage stats (Optimized & Chunked)
        usage_stats = await get_usage_stats(directus_service, encryption_service, hash_to_vault_key, months=args.months)
        
        # 5. Engagement stats (Optimized)
        engagement_stats = await get_engagement_stats(directus_service, months=args.months)
        
        # 6. Creator stats (Chunked)
        creator_stats = await get_creator_stats(directus_service, encryption_service)
        
        # 7. Output results
        if args.json:
            output = {
                "signup_stats": signup_stats, "financial_stats": financial_stats,
                "usage_stats": usage_stats, "engagement_stats": engagement_stats,
                "creator_stats": creator_stats, "generated_at": datetime.now().isoformat()
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            print(format_output(signup_stats, financial_stats, usage_stats, engagement_stats, creator_stats, args.weeks, args.months))
            
    except Exception as e:
        logger.error(f"Error during stats generation: {e}", exc_info=True)
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"❌ Error: {str(e)}")
    finally:
        await sm.aclose()
        await directus_service.close()

if __name__ == "__main__":
    asyncio.run(main())
