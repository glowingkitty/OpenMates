//! Bounded Brevo receipt policy shared by updates and runtime notifications.
use serde_json::Value;
pub(super) fn accepted(status: u16, response: &Value, request: &Value) -> bool {
    if (200..300).contains(&status) {
        return response["messageId"]
            .as_str()
            .is_some_and(|id| !id.trim().is_empty());
    }
    status == 400
        && response["code"] == "duplicate_parameter"
        && request["headers"]["idempotencyKey"]
            .as_str()
            .is_some_and(|id| uuid::Uuid::parse_str(id).is_ok())
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn lost_success_then_duplicate_under_the_same_durable_key_is_accepted() {
        let id = "58a626aa-0137-4a74-899a-c5d53dcc4d39";
        let request = json!({"headers":{"idempotencyKey":id},"subject":"fixture"});
        let attempts = [None, Some((400, json!({"code":"duplicate_parameter"})))];
        let mut accepted_at = None;
        for (index, response) in attempts.into_iter().enumerate() {
            assert_eq!(request["headers"]["idempotencyKey"], id);
            if response.is_some_and(|(status, response)| accepted(status, &response, &request)) {
                accepted_at = Some(index + 1);
                break;
            }
        }
        assert_eq!(accepted_at, Some(2));
        assert!(!accepted(
            400,
            &json!({"code":"duplicate_parameter"}),
            &json!({})
        ));
        assert!(!accepted(
            400,
            &json!({"code":"duplicate_parameter"}),
            &json!({"headers":{"idempotencyKey":"invalid"}})
        ));
        assert!(!accepted(
            400,
            &json!({"code":"invalid_parameter"}),
            &request
        ));
        assert!(!accepted(201, &json!({}), &request));
        assert!(accepted(
            201,
            &json!({"messageId":"accepted-fixture"}),
            &request
        ));
    }
}
