//! Language-neutral wire vector -> public Rust API-key SDK call. Shared by the
//! conformance example and `tests/sdk_operations_a.rs` so both execute the same
//! mapping for `sdk-api-key-operations.json` and `sdk-api-key-domains-b.json`.
// contract-test-file: tooling
use openmates_sdk::sdk_finance::CheckAccountsOptions;
use openmates_sdk::sdk_inspirations::InspirationsOptions;
use openmates_sdk::sdk_new_chat_suggestions::NewChatSuggestionsOptions;
use openmates_sdk::sdk_settings::ModelDefaults;
use openmates_sdk::{Error, OpenMates};
use serde_json::Value;

/// Why a vector could not be mapped onto a Rust call (fixture shape only).
pub type Shape = String;

fn text(args: &[Value], index: usize) -> Result<String, Shape> {
    args.get(index)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| format!("string argument {index}"))
}
fn arg(args: &[Value], index: usize) -> Result<Value, Shape> {
    args.get(index)
        .cloned()
        .ok_or_else(|| format!("argument {index}"))
}
fn kw(kwargs: &Value, name: &str) -> Option<String> {
    kwargs[name].as_str().map(str::to_owned)
}
fn required(kwargs: &Value, name: &str) -> Result<String, Shape> {
    kw(kwargs, name).ok_or_else(|| format!("keyword {name}"))
}

/// Execute one vector operation; the outer error is a fixture-shape problem, the
/// inner one the SDK's own result.
pub async fn dispatch(
    c: &OpenMates,
    op: &str,
    args: &[Value],
    kwargs: &Value,
    confirmed: bool,
) -> Result<Result<Value, Error>, Shape> {
    Ok(match op {
        "billing.overview" => c.billing().overview().await,
        "billing.buyer_address" => c.billing().buyer_address().await,
        "billing.save_buyer_address" => c.billing().save_buyer_address(Some(arg(args, 0)?)).await,
        "billing.usage_details" => {
            let (kind, identifier, month) = (
                required(kwargs, "type")?,
                required(kwargs, "identifier")?,
                required(kwargs, "year_month")?,
            );
            c.billing().usage_details(&kind, &identifier, &month).await
        }
        "billing.chat_total" => c.billing().chat_total(&text(args, 0)?).await,
        "billing.usage_summaries" => c.billing().usage_summaries().await,
        "billing.usage_daily" => c.billing().usage_daily().await,
        "billing.create_bank_transfer_order" => {
            let amount = arg(args, 0)?.as_i64().ok_or("integer amount")?;
            c.billing()
                .create_bank_transfer_order(amount, None, None)
                .await
        }
        "billing.bank_transfer_status" => c.billing().bank_transfer_status(&text(args, 0)?).await,
        "billing.list_bank_transfer_orders" => c.billing().list_bank_transfer_orders().await,
        "billing.list_invoices" => c.billing().list_invoices().await,
        "billing.request_refund" => {
            c.billing()
                .request_refund(&text(args, 0)?, confirmed, None)
                .await
        }
        "billing.redeem_gift_card" => c.billing().redeem_gift_card(&text(args, 0)?).await,
        "billing.list_redeemed_gift_cards" => c.billing().list_redeemed_gift_cards().await,
        "billing.gift_card_purchase_status" => {
            c.billing().gift_card_purchase_status(&text(args, 0)?).await
        }
        "billing.list_purchased_gift_cards" => c.billing().list_purchased_gift_cards().await,
        "billing.set_low_balance_auto_topup" => {
            c.billing().set_low_balance_auto_topup(arg(args, 0)?).await
        }
        "settings.set_language" => c.settings().set_language(&text(args, 0)?).await,
        "settings.set_dark_mode" => {
            let enabled = arg(args, 0)?.as_bool().ok_or("boolean argument")?;
            c.settings().set_dark_mode(enabled).await
        }
        "settings.set_font" => c.settings().set_font(&text(args, 0)?).await,
        "settings.set_model_defaults" => {
            c.settings()
                .set_model_defaults(ModelDefaults {
                    default_ai_model_simple: kw(kwargs, "default_ai_model_simple"),
                    default_ai_model_complex: kw(kwargs, "default_ai_model_complex"),
                    default_ai_model_most_demanding: kw(kwargs, "default_ai_model_most_demanding"),
                })
                .await
        }
        "settings.set_chat_auto_delete" => c.settings().set_chat_auto_delete(&text(args, 0)?).await,
        "reminders.list" => c.reminders().list().await,
        "reminders.update" => c.reminders().update(&text(args, 0)?, arg(args, 1)?).await,
        "reminders.delete" => c.reminders().delete(&text(args, 0)?, confirmed).await,
        "notifications.status" => c.notifications().status().await,
        "notifications.list" => {
            let limit = match kwargs.get("limit") {
                None | Some(Value::Null) => None,
                Some(value) => Some(
                    value
                        .as_u64()
                        .and_then(|limit| u32::try_from(limit).ok())
                        .ok_or("u32 limit")?,
                ),
            };
            c.notifications().list(limit).await
        }
        "feedback.assistant_response" => {
            let rating = kwargs["rating"].as_i64().ok_or("integer rating")?;
            c.feedback().assistant_response(rating).await
        }
        "inspirations.list" => {
            c.inspirations()
                .list(InspirationsOptions {
                    language: kw(kwargs, "language"),
                })
                .await
        }
        "new_chat_suggestions.list" => {
            let limit = match kwargs.get("limit") {
                None | Some(Value::Null) => None,
                Some(value) => Some(
                    value
                        .as_u64()
                        .and_then(|limit| u32::try_from(limit).ok())
                        .ok_or("u32 limit")?,
                ),
            };
            c.new_chat_suggestions()
                .list(NewChatSuggestionsOptions { limit })
                .await
        }
        "learning_mode.status" => c.learning_mode().status().await,
        "learning_mode.enable" => {
            let (age_group, passcode) = (
                required(kwargs, "age_group")?,
                required(kwargs, "passcode")?,
            );
            c.learning_mode()
                .enable(
                    &age_group,
                    &passcode,
                    kwargs["collaborative_build"].as_bool(),
                )
                .await
        }
        "learning_mode.collaborative" => {
            let enabled = args
                .first()
                .and_then(Value::as_bool)
                .ok_or("bool argument 0")?;
            c.learning_mode()
                .collaborative(enabled, kw(kwargs, "passcode").as_deref())
                .await
        }
        "learning_mode.disable" => c.learning_mode().disable(&text(args, 0)?).await,
        "benchmark.run" => c.benchmark().run(arg(args, 0)?).await,
        "benchmark.estimate" => c.benchmark().estimate(arg(args, 0)?).await,
        "finance.check_accounts" => {
            let options = CheckAccountsOptions {
                prompt_injection_protection: kwargs["prompt_injection_protection"].as_bool(),
                ..Default::default()
            };
            c.finance().check_accounts(arg(args, 0)?, options).await
        }
        other => {
            return Err(format!(
                "fixture operation without a Rust dispatcher: {other}"
            ));
        }
    })
}
