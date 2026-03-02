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


def _collect_json_fields(stats: dict) -> dict:
    """
    Extracts namespaced JSON sub-fields from a flat stats dict.

    Fields stored as "{prefix}:{sub_key}" are grouped into nested dicts.
    Example:
        {"usage_entries_by_app:ai": 500, "purchases_by_provider:stripe": 80}
        → {"usage_entries_by_app": {"ai": 500}, "purchases_by_provider": {"stripe": 80}}
    """
    result: dict = {}
    for key, value in stats.items():
        if ":" in key:
            prefix, sub_key = key.split(":", 1)
            if prefix not in result:
                result[prefix] = {}
            result[prefix][sub_key] = int(value)
    return result


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
        # Collect JSON sub-fields: any key matching "prefix:sub_key" is aggregated
        # into a JSON object stored in the corresponding column (e.g. usage_entries_by_app)
        _json_fields = _collect_json_fields(daily_incremental)

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
            # Phase 2: Usage entries
            "usage_entries_created": daily_incremental.get("usage_entries_created", 0),
            "usage_entries_by_app": json.dumps(_json_fields.get("usage_entries_by_app", {})),
            # Phase 3: Financial analytics
            "purchase_count": daily_incremental.get("purchase_count", 0),
            "purchases_by_provider": json.dumps(_json_fields.get("purchases_by_provider", {})),
            "gift_cards_created": daily_incremental.get("gift_cards_created", 0),
            "gift_cards_redeemed": daily_incremental.get("gift_cards_redeemed", 0),
            "subscription_creations": daily_incremental.get("subscription_creations", 0),
            "subscription_cancellations": daily_incremental.get("subscription_cancellations", 0),
            # Phase 6: Token/cost tracking
            "total_input_tokens": daily_incremental.get("total_input_tokens", 0),
            "total_output_tokens": daily_incremental.get("total_output_tokens", 0),
            # Snapshots
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

        # 6. Flush signup funnel data into signup_funnel_daily collection
        await flush_signup_funnel(task, today_str, daily_incremental)

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
            
        # Aggregate — sum all daily values
        # For JSON fields (stored as JSON strings), we aggregate by summing sub-keys
        def _sum_json_field(field_name: str) -> str:
            """Merges JSON objects across dailies by summing each key."""
            merged: dict = {}
            for d in dailies:
                val = d.get(field_name)
                if val:
                    try:
                        sub_dict = json.loads(val) if isinstance(val, str) else val
                        for k, v in sub_dict.items():
                            merged[k] = merged.get(k, 0) + int(v)
                    except Exception:
                        pass
            return json.dumps(merged)

        latest_daily = sorted(dailies, key=lambda x: x["date"])[-1]

        # Directus may return numeric fields as int or as str (e.g. if stored as a string type).
        # Wrap every sum operand with int(...or 0) to guarantee type-safe addition regardless
        # of what the CMS returns.
        def _int(val) -> int:
            try:
                return int(val or 0)
            except (TypeError, ValueError):
                return 0

        monthly_payload = {
            "year_month": year_month,
            "new_users_registered": sum(_int(d.get("new_users_registered")) for d in dailies),
            "new_users_finished_signup": sum(_int(d.get("new_users_finished_signup")) for d in dailies),
            "income_eur_cents": sum(_int(d.get("income_eur_cents")) for d in dailies),
            "credits_sold": sum(_int(d.get("credits_sold")) for d in dailies),
            "credits_used": sum(_int(d.get("credits_used")) for d in dailies),
            "messages_sent": sum(_int(d.get("messages_sent")) for d in dailies),
            "chats_created": sum(_int(d.get("chats_created")) for d in dailies),
            "embeds_created": sum(_int(d.get("embeds_created")) for d in dailies),
            # Phase 2: Usage entries
            "usage_entries_created": sum(_int(d.get("usage_entries_created")) for d in dailies),
            "usage_entries_by_app": _sum_json_field("usage_entries_by_app"),
            # Phase 3: Financial analytics
            "purchase_count": sum(_int(d.get("purchase_count")) for d in dailies),
            "purchases_by_provider": _sum_json_field("purchases_by_provider"),
            "gift_cards_created": sum(_int(d.get("gift_cards_created")) for d in dailies),
            "gift_cards_redeemed": sum(_int(d.get("gift_cards_redeemed")) for d in dailies),
            "subscription_creations": sum(_int(d.get("subscription_creations")) for d in dailies),
            "subscription_cancellations": sum(_int(d.get("subscription_cancellations")) for d in dailies),
            # Phase 6: Token/cost tracking
            "total_input_tokens": sum(_int(d.get("total_input_tokens")) for d in dailies),
            "total_output_tokens": sum(_int(d.get("total_output_tokens")) for d in dailies),
            # Snapshots: Take the latest one from the dailies
            "liability_total": _int(latest_daily.get("liability_total")),
            "active_subscriptions": _int(latest_daily.get("active_subscriptions")),
            "total_regular_users": _int(latest_daily.get("total_regular_users")),
            "updated_at": datetime.now().isoformat()
        }
        
        existing_monthly = await task.directus_service.analytics.get_server_stats_monthly(year_month)
        if existing_monthly:
            await task.directus_service.analytics.update_server_stats_monthly(existing_monthly["id"], monthly_payload)
        else:
            await task.directus_service.analytics.create_server_stats_monthly(monthly_payload)
            
    except Exception as e:
        logger.error(f"Error updating monthly stats for {year_month}: {e}")


async def flush_signup_funnel(task: BaseServiceTask, today_str: str, daily_stats: dict) -> None:
    """
    Flushes signup funnel step counters from Redis into the signup_funnel_daily Directus collection.

    The counters are stored in the same daily Redis hash as other stats (prefixed with "signup_step_").
    This function extracts them and upserts the signup_funnel_daily record.
    """
    try:
        # Map Redis field names → Directus column names
        funnel_payload = {
            "date": today_str,
            "started_basics": daily_stats.get("signup_step_started_basics", 0),
            "email_confirmed": daily_stats.get("signup_step_email_confirmed", 0),
            "auth_password_setup": daily_stats.get("signup_step_auth_password_setup", 0),
            "auth_passkey_setup": daily_stats.get("signup_step_auth_passkey_setup", 0),
            "recovery_key_saved": daily_stats.get("signup_step_recovery_key_saved", 0),
            "reached_payment": daily_stats.get("signup_step_reached_payment", 0),
            # payment_completed is new_users_finished_signup (already tracked separately)
            "payment_completed": daily_stats.get("new_users_finished_signup", 0),
            "payment_completed_eu": daily_stats.get("payment_completed_eu", 0),
            "payment_completed_non_eu": daily_stats.get("payment_completed_non_eu", 0),
            "auto_topup_setup": daily_stats.get("signup_step_auto_topup_setup", 0),
        }

        # Only flush if any funnel step was recorded
        if not any(v > 0 for k, v in funnel_payload.items() if k != "date" and isinstance(v, int)):
            return

        existing_records = await task.directus_service.get_items(
            "signup_funnel_daily",
            params={"filter": {"date": {"_eq": today_str}}, "limit": 1}
        )
        if existing_records:
            await task.directus_service.update_item(
                "signup_funnel_daily",
                existing_records[0]["id"],
                funnel_payload,
                admin_required=True,
            )
        else:
            await task.directus_service.create_item(
                "signup_funnel_daily",
                funnel_payload,
                admin_required=True,
            )
    except Exception as e:
        logger.error(f"Error flushing signup funnel for {today_str}: {e}", exc_info=True)
