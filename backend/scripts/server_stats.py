#!/usr/bin/env python3
"""
Script to display server-wide statistics including user signups, financial metrics,
and credit usage over time.

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
from typing import Dict, Any, List, Optional, Tuple
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

async def get_signup_stats(directus_service: DirectusService) -> Dict[str, Any]:
    """Get statistics about user signups and subscriptions."""
    stats = {
        'total_users': 0,
        'finished_signup': 0,
        'in_signup_flow': 0,
        'just_registered': 0,
        'subscriptions_active': 0,
        'auto_topup_enabled': 0
    }
    
    try:
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        headers = {"Authorization": f"Bearer {admin_token}"}
        url = f"{directus_service.base_url}/users"
        
        # 1. Total non-admin users
        params_total = {
            'filter[is_admin][_eq]': False,
            'limit': 1,
            'meta': 'filter_count'
        }
        resp_total = await directus_service._make_api_request("GET", url, params=params_total, headers=headers)
        stats['total_users'] = resp_total.json().get('meta', {}).get('filter_count', 0) if resp_total.status_code == 200 else 0
        
        # 2. Get unique user hashes who have invoices (purchased credits)
        invoices = await directus_service.get_items('invoices', params={'fields': 'user_id_hash', 'limit': -1}, admin_required=True)
        invoice_hashes = set(inv.get('user_id_hash') for inv in (invoices or []) if inv.get('user_id_hash'))
        
        # 3. Get unique user hashes who redeemed gift cards
        redeemed = await directus_service.get_items('redeemed_gift_cards', params={'fields': 'user_id_hash', 'limit': -1}, admin_required=True)
        redeemed_hashes = set(r.get('user_id_hash') for r in (redeemed or []) if r.get('user_id_hash'))
        
        # Combined set of "Finished Signup" users
        finished_hashes = invoice_hashes | redeemed_hashes
        
        # 4. Get all existing users to categorize them and check subscriptions
        params_users = {
            'filter[is_admin][_eq]': False,
            'fields': 'id,last_opened,stripe_subscription_id,subscription_status,auto_topup_low_balance_enabled',
            'limit': -1
        }
        resp_users = await directus_service._make_api_request("GET", url, params=params_users, headers=headers)
        all_users = resp_users.json().get('data', []) if resp_users.status_code == 200 else []
        
        finished_count = 0
        in_flow = 0
        just_registered = 0
        subs_active = 0
        auto_topup = 0
        
        for u in all_users:
            u_id = u.get('id')
            if not u_id: continue
            u_hash = hashlib.sha256(u_id.encode()).hexdigest()
            
            # Subscriptions & Auto Top-up
            if u.get('stripe_subscription_id') and u.get('subscription_status') == 'active':
                subs_active += 1
            if u.get('auto_topup_low_balance_enabled'):
                auto_topup += 1
            
            # Count as finished if they have an invoice or redeemed a gift card
            if u_hash in finished_hashes:
                finished_count += 1
                continue
                
            last_opened = u.get('last_opened')
            if last_opened and last_opened.startswith('/signup/'):
                in_flow += 1
            elif not last_opened:
                just_registered += 1
        
        stats['finished_signup'] = finished_count
        stats['in_signup_flow'] = in_flow
        stats['just_registered'] = just_registered
        stats['subscriptions_active'] = subs_active
        stats['auto_topup_enabled'] = auto_topup
            
    except Exception as e:
        logger.error(f"Error fetching signup stats: {e}")
        
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
    """Get financial statistics from invoices and user balances."""
    
    # Calculate cutoff dates
    today = date.today()
    week_cutoff = today - timedelta(weeks=weeks)
    month_cutoff = today - timedelta(days=months * 30)
    cutoff = min(week_cutoff, month_cutoff)
    
    try:
        # 1. Fetch Invoices
        params_inv = {
            'filter[date][_gte]': cutoff.isoformat(),
            'fields': 'id,user_id_hash,date,encrypted_amount,encrypted_credits_purchased,is_gift_card,refund_status',
            'limit': -1
        }
        invoices = await directus_service.get_items('invoices', params=params_inv, admin_required=True)
        
        # 2. Calculate Outstanding Liability (decrypted balances)
        balance_tasks = [encryption_service.decrypt_with_user_key(bal, v_id) for bal, v_id in user_balances]
        balances = await asyncio.gather(*balance_tasks)
        total_outstanding_credits = sum(int(b) for b in balances if b and b.isdigit())
        
        # 3. Decrypt Invoices
        invoice_tasks = []
        for inv in (invoices or []):
            u_hash = inv.get('user_id_hash')
            v_key_id = hash_to_vault_key.get(u_hash)
            if v_key_id:
                invoice_tasks.append(process_invoice(inv, v_key_id, encryption_service))
        
        decrypted_results = await asyncio.gather(*invoice_tasks)
        decrypted_invoices = [r for r in decrypted_results if r]
        
        # Aggregation
        stats = {
            "weekly": defaultdict(lambda: {"income": 0, "credits": 0}),
            "monthly": defaultdict(lambda: {"income": 0, "credits": 0}),
            "total_income": 0,
            "total_credits": 0,
            "liability_credits": total_outstanding_credits,
            "arpu": 0
        }
        
        for inv in decrypted_invoices:
            d = inv['date']
            week_id = d.strftime("%Y-W%W")
            month_id = d.strftime("%Y-%m")
            amount = inv['amount']
            credits_purchased = inv['credits']
            
            if inv.get('refund_status') == 'completed':
                continue
                
            stats["weekly"][week_id]["income"] += amount / 100.0
            stats["weekly"][week_id]["credits"] += credits_purchased
            
            stats["monthly"][month_id]["income"] += amount / 100.0
            stats["monthly"][month_id]["credits"] += credits_purchased
            
            stats["total_income"] += amount / 100.0
            stats["total_credits"] += credits_purchased
            
        if finished_signup_count > 0:
            stats["arpu"] = stats["total_income"] / finished_signup_count
            
        return stats
        
    except Exception as e:
        logger.error(f"Error fetching financial stats: {e}", exc_info=True)
        return {"weekly": {}, "monthly": {}, "total_income": 0, "total_credits": 0, "liability_credits": 0, "arpu": 0}

async def process_invoice(inv: Dict[str, Any], vault_key_id: str, encryption_service: EncryptionService) -> Optional[Dict[str, Any]]:
    """Decrypt and process a single invoice."""
    try:
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
    """Get usage statistics including detailed skill breakdown for current month."""
    stats = {
        "monthly": defaultdict(lambda: {"credits": 0, "requests": 0}),
        "skill_breakdown": defaultdict(lambda: {"credits": 0, "requests": 0}),
        "total_used": 0,
        "total_requests": 0
    }
    
    today = date.today()
    month_start = datetime(today.year, today.month, 1)
    month_start_ts = int(month_start.timestamp())
    
    # 1. Fetch Monthly Summaries for historical data
    year_months = []
    for i in range(months):
        month_date = today - timedelta(days=i * 30)
        year_months.append(month_date.strftime("%Y-%m"))
        
    try:
        params_sum = {
            'filter[year_month][_in]': year_months,
            'fields': 'year_month,total_credits,entry_count',
            'limit': -1
        }
        summaries = await directus_service.get_items('usage_monthly_app_summaries', params=params_sum, admin_required=True)
        for s in summaries:
            ym = s.get('year_month')
            stats["monthly"][ym]["credits"] += s.get('total_credits', 0)
            stats["monthly"][ym]["requests"] += s.get('entry_count', 0)
            
        all_summaries = await directus_service.get_items('usage_monthly_app_summaries', params={'fields': 'total_credits,entry_count', 'limit': -1}, admin_required=True)
        stats["total_used"] = sum(s.get('total_credits', 0) for s in all_summaries)
        stats["total_requests"] = sum(s.get('entry_count', 0) for s in all_summaries)

        # 2. Fetch raw usage for CURRENT MONTH to get skill breakdown
        params_raw = {
            'filter[created_at][_gte]': month_start_ts,
            'fields': 'user_id_hash,app_id,skill_id,encrypted_credits_costs_total',
            'limit': -1
        }
        raw_usage = await directus_service.get_items('usage', params=params_raw, admin_required=True)
        
        if raw_usage:
            # Group by user to decrypt credits
            decrypt_tasks = []
            for entry in raw_usage:
                u_hash = entry.get('user_id_hash')
                v_key_id = hash_to_vault_key.get(u_hash)
                enc_credits = entry.get('encrypted_credits_costs_total')
                
                if v_key_id and enc_credits:
                    decrypt_tasks.append(encryption_service.decrypt_with_user_key(enc_credits, v_key_id))
                else:
                    decrypt_tasks.append(asyncio.sleep(0, result="0"))
            
            decrypted_credits = await asyncio.gather(*decrypt_tasks)
            
            for entry, credit_val in zip(raw_usage, decrypted_credits):
                app = entry.get('app_id', 'unknown')
                skill = entry.get('skill_id', 'unknown')
                skill_key = f"{app}.{skill}"
                
                credits = int(credit_val) if credit_val and credit_val.isdigit() else 0
                stats["skill_breakdown"][skill_key]["credits"] += credits
                stats["skill_breakdown"][skill_key]["requests"] += 1
                
    except Exception as e:
        logger.error(f"Error fetching usage stats: {e}", exc_info=True)
        
    return stats

async def get_creator_stats(directus_service: DirectusService, encryption_service: EncryptionService) -> Dict[str, Any]:
    """Get statistics about creator income liability."""
    stats = {
        "reserved_credits": 0,
        "claimed_credits": 0,
        "total_entries": 0
    }
    
    try:
        params = {
            'fields': 'status,encrypted_credits_reserved',
            'limit': -1
        }
        entries = await directus_service.get_items('creator_income', params=params, admin_required=True)
        if not entries:
            return stats
            
        stats["total_entries"] = len(entries)
        
        # System key decryption
        tasks = []
        for e in entries:
            enc_credits = e.get('encrypted_credits_reserved')
            if enc_credits:
                tasks.append(encryption_service.decrypt(enc_credits, key_name=CREATOR_INCOME_ENCRYPTION_KEY))
            else:
                tasks.append(asyncio.sleep(0, result=None)) # Placeholder
                
        decrypted_credits = await asyncio.gather(*tasks)
        
        for e, credits_str in zip(entries, decrypted_credits):
            if not credits_str or not credits_str.isdigit():
                continue
            
            credits = int(credits_str)
            if e.get('status') == 'reserved':
                stats["reserved_credits"] += credits
            elif e.get('status') == 'claimed':
                stats["claimed_credits"] += credits
                
    except Exception as e:
        logger.error(f"Error fetching creator stats: {e}")
        
    return stats

def format_output(
    signup_stats: Dict[str, Any],
    financial_stats: Dict[str, Any],
    usage_stats: Dict[str, Any],
    creator_stats: Dict[str, Any],
    weeks: int,
    months: int
) -> str:
    """Format the report as a string."""
    lines = []
    lines.append("=" * 100)
    lines.append("SERVER STATISTICS REPORT")
    lines.append("=" * 100)
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)
    
    # Growth & Engagement Section
    lines.append("-" * 100)
    lines.append("USER GROWTH & ENGAGEMENT")
    lines.append("-" * 100)
    lines.append(f"  Total Regular Users:   {signup_stats.get('total_users', 0):>10,}")
    lines.append(f"  Finished Signup*:      {signup_stats.get('finished_signup', 0):>10,}")
    lines.append(f"  In Signup Flow:        {signup_stats.get('in_signup_flow', 0):>10,}")
    lines.append(f"  Just Registered:       {signup_stats.get('just_registered', 0):>10,}")
    lines.append("")
    lines.append(f"  Active Subscriptions:  {signup_stats.get('subscriptions_active', 0):>10,}")
    lines.append(f"  Auto Top-up Enabled:   {signup_stats.get('auto_topup_enabled', 0):>10,}")
    lines.append("")
    lines.append("  * Finished Signup: user has at least one invoice or redeemed gift card.")
    lines.append("")
    
    # Financial Section
    lines.append("-" * 100)
    lines.append(f"FINANCIAL OVERVIEW")
    lines.append("-" * 100)
    lines.append(f"  Total Income (L6M):    {financial_stats.get('total_income', 0):>10.2f} EUR")
    lines.append(f"  ARPU (Lifetime)*:      {financial_stats.get('arpu', 0):>10.2f} EUR")
    lines.append("")
    lines.append(f"  User Credit Balance (Liability): {financial_stats.get('liability_credits', 0):>10,} Credits")
    lines.append(f"  Creator Reserved Credits:        {creator_stats.get('reserved_credits', 0):>10,} Credits")
    lines.append("")
    lines.append("  * ARPU: Average Revenue Per User (Total Income / Finished Signup Count)")
    lines.append("")
    
    # Skill Breakdown Section
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
    
    # Comparison Section - Monthly
    lines.append("-" * 100)
    lines.append(f"MONTHLY DEVELOPMENT (Last {months} Months)")
    lines.append("-" * 100)
    lines.append(f"  {'Month':<10} | {'Income (EUR)':>12} | {'Credits Sold':>15} | {'Credits Used':>15} | {'Requests':>10}")
    lines.append("-" * 100)
    
    all_months = sorted(list(set(financial_stats["monthly"].keys()) | set(usage_stats["monthly"].keys())), reverse=True)[:months]
    
    for month in all_months:
        f_stat = financial_stats["monthly"].get(month, {"income": 0, "credits": 0})
        u_stat = usage_stats["monthly"].get(month, {"credits": 0, "requests": 0})
        lines.append(f"  {month:<10} | {f_stat['income']:>12.2f} | {f_stat['credits']:>15,} | {u_stat['credits']:>15,} | {u_stat['requests']:>10,}")
    
    lines.append("")
    
    # Weekly Section
    lines.append("-" * 100)
    lines.append(f"WEEKLY DEVELOPMENT (Last {weeks} Weeks)")
    lines.append("-" * 100)
    lines.append(f"  {'Week':<10} | {'Income (EUR)':>12} | {'Credits Sold':>15}")
    lines.append("-" * 100)
    
    all_weeks = sorted(financial_stats["weekly"].keys(), reverse=True)[:weeks]
    for week in all_weeks:
        f_stat = financial_stats["weekly"].get(week, {"income": 0, "credits": 0})
        lines.append(f"  {week:<10} | {f_stat['income']:>12.2f} | {f_stat['credits']:>15,}")
        
    lines.append("")
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    
    return "\n".join(lines)

async def main():
    parser = argparse.ArgumentParser(description='Server-wide statistics')
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
        # 1. Signup stats
        signup_stats = await get_signup_stats(directus_service)
        
        # 2. Get User Map (Needed for all decryption tasks)
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        headers = {"Authorization": f"Bearer {admin_token}"}
        url = f"{directus_service.base_url}/users"
        params_users = {'fields': 'id,vault_key_id,encrypted_credit_balance', 'limit': -1, 'filter[is_admin][_eq]': False}
        
        resp_users = await directus_service._make_api_request("GET", url, params=params_users, headers=headers)
        all_users = resp_users.json().get('data', []) if resp_users.status_code == 200 else []
        
        hash_to_vault_key = {}
        user_balances = []
        for u in all_users:
            u_id = u.get('id')
            v_key_id = u.get('vault_key_id')
            if u_id:
                u_hash = hashlib.sha256(u_id.encode()).hexdigest()
                hash_to_vault_key[u_hash] = v_key_id
                if v_key_id and u.get('encrypted_credit_balance'):
                    user_balances.append((u.get('encrypted_credit_balance'), v_key_id))

        # 3. Financial stats
        financial_stats = await get_financial_stats(
            directus_service, 
            encryption_service, 
            hash_to_vault_key,
            user_balances,
            weeks=args.weeks, 
            months=args.months,
            finished_signup_count=signup_stats.get('finished_signup', 0)
        )
        
        # 4. Usage stats
        usage_stats = await get_usage_stats(directus_service, encryption_service, hash_to_vault_key, months=args.months)
        
        # 5. Creator stats
        creator_stats = await get_creator_stats(directus_service, encryption_service)
        
        # 5. Output results
        if args.json:
            output = {
                "signup_stats": signup_stats,
                "financial_stats": financial_stats,
                "usage_stats": usage_stats,
                "creator_stats": creator_stats,
                "generated_at": datetime.now().isoformat()
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            output = format_output(signup_stats, financial_stats, usage_stats, creator_stats, args.weeks, args.months)
            print(output)
            
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
