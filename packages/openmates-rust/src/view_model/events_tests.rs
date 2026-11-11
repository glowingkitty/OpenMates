//! Request ids, error classification and event equality of the boundary types.
use super::*;
use crate::error::Error;

#[test]
fn request_ids_are_ordered_and_distinct_from_plain_integers() {
    assert!(RequestId(1) < RequestId(2));
    assert_eq!(RequestId(7), RequestId(7));
}

#[test]
fn core_errors_classify_without_payload() {
    assert_eq!(ViewErrorKind::from(&Error::Expired), ViewErrorKind::Expired);
    assert_eq!(
        ViewErrorKind::from(&Error::Invalid("secret detail")),
        ViewErrorKind::Invalid
    );
    assert_eq!(
        ViewErrorKind::from(&Error::Unavailable {
            code: "feature_off",
            reason: "x"
        }),
        ViewErrorKind::Unavailable {
            code: "feature_off".into()
        }
    );
}

#[test]
fn chat_open_failure_names_its_request() {
    let event = ViewEvent::ChatOpenFailed {
        request: RequestId(3),
        chat_id: "c".into(),
        error: ViewErrorKind::Offline,
    };
    assert_eq!(event, event.clone());
    assert!(matches!(
        event,
        ViewEvent::ChatOpenFailed {
            request: RequestId(3),
            ..
        }
    ));
}

#[test]
fn view_model_errors_name_record_and_field() {
    let error = ViewModelError::MissingField {
        record: "chat_row",
        field: "id",
    };
    assert_eq!(error.to_string(), "chat_row: missing field `id`");
}
