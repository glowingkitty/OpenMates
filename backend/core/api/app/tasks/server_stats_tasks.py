"""
Celery tasks for flushing cached server statistics to Directus.
"""

import logging
import asyncio
import json
from datetime import datetime, date

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

logger = logging.getLogger(__name__)

@app.task(name="server_stats.flush_to_directus", base=BaseServiceTask, bind=True)
def flush_server_stats(self):
    """
    Periodic task to flush incremental stats from Redis to Directus.
    Runs every 10 minutes.
    """
    return asyncio.run(run_flush_server_stats(self))

async def run_flush_server_stats(task: BaseServiceTask):
    log_prefix = "ServerStatsFlushTask:"
    logger.info(f"{log_prefix} Starting stats flush to Directus")
    
    try:
        await task.initialize_services()
        
        today_str = date.today().isoformat()
        current_month_str = today_str[:7] # YYYY-MM
        
        # 1. Get stats from Redis
        daily_incremental = await task.cache_service.get_daily_stats(today_str)
        total_liability = await task.cache_service.get_total_liability()
        
        # 2. Get system-wide totals (non-incremental)
        total_users = await task.directus_service.get_total_users_count()
        
        # Count active subscriptions
        active_subs_count = 0
        try:
            url = f"{task.directus_service.base_url}/users"
            params = {
                'limit': 1,
                'meta': 'filter_count',
                'filter': json.dumps({
                    '_and': [
                        {'is_admin': {'_eq': False}},
                        {'stripe_subscription_id': {'_nnull': True}},
                        {'subscription_status': {'_eq': 'active'}}
                    ]
                })
            }
            admin_token = await task.directus_service.ensure_auth_token(admin_required=True)
            headers = {"Authorization": f"Bearer {admin_token}"}
            resp = await task.directus_service._make_api_request("GET", url, params=params, headers=headers)
            if resp.status_code == 200:
                active_subs_count = resp.json().get('meta', {}).get('filter_count', 0)
        except Exception as e:
            logger.error(f"{log_prefix} Error counting active subscriptions: {e}")

        # 3. Prepare Payload for Daily Record
        daily_payload = {
            "date": today_str,
            "new_users_registered": daily_incremental.get("new_users_registered", 0),
            "new_users_finished_signup": daily_incremental.get("new_users_finished_signup", 0),
            "income_eur_cents": daily_incremental.get("income_eur_cents", 0),
            "credits_sold": daily_incremental.get("credits_sold", 0),
            "credits_used": daily_incremental.get("credits_used", 0),
            "messages_sent": daily_incremental.get("messages_sent", 0),
            "chats_created": daily_incremental.get("chats_created", 0),
            "embeds_created": daily_incremental.get("embeds_created", 0),
            "liability_total": total_liability,
            "active_subscriptions": active_subs_count,
            "total_regular_users": total_users,
            "updated_at": datetime.now().isoformat()
        }
        
        # 4. Upsert Daily Record
        existing_daily = await task.directus_service.analytics.get_server_stats_daily(today_str)
        if existing_daily:
            await task.directus_service.analytics.update_server_stats_daily(existing_daily["id"], daily_payload)
        else:
            await task.directus_service.analytics.create_server_stats_daily(daily_payload)
            
        # 5. Update Monthly Record (Aggregation)
        # For monthly, we aggregate all daily records for this month
        await update_monthly_stats(task, current_month_str)
        
        logger.info(f"{log_prefix} Successfully flushed stats for {today_str}")
        return {"success": True, "date": today_str}
        
    except Exception as e:
        logger.error(f"{log_prefix} Stats flush failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()

async def update_monthly_stats(task: BaseServiceTask, year_month: str):
    """Aggregates all daily records for a month into the monthly record."""
    try:
        # Fetch all daily records for this month
        params = {
            "filter": {"date": {"_starts_with": year_month}},
            "limit": -1
        }
        dailies = await task.directus_service.get_items("server_stats_global_daily", params=params)
        
        if not dailies:
            return
            
        # Aggregate
        monthly_payload = {
            "year_month": year_month,
            "new_users_registered": sum(d.get("new_users_registered", 0) for d in dailies),
            "new_users_finished_signup": sum(d.get("new_users_finished_signup", 0) for d in dailies),
            "income_eur_cents": sum(int(d.get("income_eur_cents", 0)) for d in dailies),
            "credits_sold": sum(d.get("credits_sold", 0) for d in dailies),
            "credits_used": sum(d.get("credits_used", 0) for d in dailies),
            "messages_sent": sum(d.get("messages_sent", 0) for d in dailies),
            "chats_created": sum(d.get("chats_created", 0) for d in dailies),
            "embeds_created": sum(d.get("embeds_created", 0) for d in dailies),
            # Snapshots: Take the latest one from the dailies
            "liability_total": sorted(dailies, key=lambda x: x["date"])[-1].get("liability_total", 0),
            "active_subscriptions": sorted(dailies, key=lambda x: x["date"])[-1].get("active_subscriptions", 0),
            "total_regular_users": sorted(dailies, key=lambda x: x["date"])[-1].get("total_regular_users", 0),
            "updated_at": datetime.now().isoformat()
        }
        
        existing_monthly = await task.directus_service.analytics.get_server_stats_monthly(year_month)
        if existing_monthly:
            await task.directus_service.analytics.update_server_stats_monthly(existing_monthly["id"], monthly_payload)
        else:
            await task.directus_service.analytics.create_server_stats_monthly(monthly_payload)
            
    except Exception as e:
        logger.error(f"Error updating monthly stats for {year_month}: {e}")
