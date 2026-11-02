//! Best-effort zeroization of owned JSON values before drop. Platform neutral.
use serde_json::Value;
use zeroize::Zeroize;

pub(crate) fn wipe_json_value(value: &mut Value) {
    match value {
        Value::String(s) => s.zeroize(),
        Value::Array(a) => {
            for v in a {
                wipe_json_value(v)
            }
        }
        Value::Object(o) => {
            for (mut key, mut v) in std::mem::take(o) {
                key.zeroize();
                wipe_json_value(&mut v)
            }
        }
        _ => {}
    }
    *value = Value::Null;
}
