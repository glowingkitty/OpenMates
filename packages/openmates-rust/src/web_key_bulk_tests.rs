//! Replays web_key_bulk_ts_vectors.json (generated from db/chatKeyBulkPlan.ts)
//! through the Rust bulk key load planning.
use crate::web_key_bulk::{batch_ranges, retry_step, BATCH_SIZE, MAX_RETRIES, RETRY_DELAY_MS};
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_key_bulk_ts_vectors.json")).expect("vectors parse")
}

#[test]
fn constants_equal_typescript() {
    let v = vectors();
    assert_eq!(BATCH_SIZE as u64, v["batchSize"].as_u64().expect("batchSize"));
    assert_eq!(u64::from(RETRY_DELAY_MS), v["retryDelayMs"].as_u64().expect("delay"));
    assert_eq!(u64::from(MAX_RETRIES), v["maxRetries"].as_u64().expect("max"));
}

#[test]
fn batch_ranges_equal_typescript() {
    for case in vectors()["batches"].as_array().expect("cases") {
        let count = usize::try_from(case["count"].as_u64().expect("count")).expect("usize");
        let want: Vec<(usize, usize)> = case["ranges"]
            .as_array()
            .expect("ranges")
            .iter()
            .map(|r| {
                (
                    usize::try_from(r[0].as_u64().expect("start")).expect("usize"),
                    usize::try_from(r[1].as_u64().expect("end")).expect("usize"),
                )
            })
            .collect();
        assert_eq!(batch_ranges(count), want, "count {count}");
    }
}

#[test]
fn retry_steps_equal_typescript() {
    for case in vectors()["retries"].as_array().expect("cases") {
        let count = u32::try_from(case["retryCount"].as_u64().expect("count")).expect("u32");
        let available = case["masterKeyAvailable"].as_bool().expect("available");
        assert_eq!(
            retry_step(count, available).as_str(),
            case["step"].as_str().expect("step"),
            "retry {count} available {available}"
        );
    }
}
