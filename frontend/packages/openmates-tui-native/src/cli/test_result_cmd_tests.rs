//! Output tests for `embeds test-result`: JSON carries render model and asset ids, text escapes sandbox escapes.
use super::*;

fn read(content: &str) -> Value {
    json!({"embed_id": "11111111-1111-4111-8111-111111111111", "version_number": 2, "content": content})
}

const CLI_RESULT: &str = r#"{"kind":"cli","target":"e2b","run_status":"passed","passed":1,
"steps":[{"name":"add","status":"passed","command":"recipes add","output":"\u001b[31mred\u001b[0m"}],
"evidence":[{"kind":"terminal_cast","path":"outputs/test-run/terminal.cast","asset_id":"cast-1"}]}"#;

#[test]
fn json_output_has_render_model_and_evidence_asset_ids() {
    let out = output(true, &read(CLI_RESULT)).ok().expect("renders");
    let value: Value = serde_json::from_str(&out.stdout).unwrap();
    assert_eq!(value["render"]["layout"]["layout"], "terminal");
    assert_eq!(value["render"]["layout"]["cast"]["asset_id"], "cast-1");
    assert_eq!(value["test_result"]["kind"], "cli");
}

#[test]
fn text_output_escapes_terminal_sequences_from_the_sandbox() {
    let out = output(false, &read(CLI_RESULT)).ok().expect("renders");
    assert!(out.stdout.contains("$ recipes add"));
    assert!(out.stdout.contains("\\u001b[31mred"));
    assert!(out.stdout.contains("asset cast-1"));
}

#[test]
fn non_test_result_content_is_rejected_with_a_stable_code() {
    let Err(error) = output(true, &read(r#"{"language":"python"}"#)) else {
        panic!("must be rejected")
    };
    assert!(matches!(
        error,
        CliError::Contract {
            code: "test_result_invalid",
            ..
        }
    ));
}
