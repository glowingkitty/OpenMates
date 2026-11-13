//! Decode and render-model tests for the test result embed: TOON fixtures for
//! the unit, browser and cli kinds in the shape the backend writes.
use super::*;

const UNIT: &str = "type: test_result
app_id: code
skill_id: test_result
status: finished
kind: unit
target: e2b
run_status: failed
exit_code: 1
duration_ms: 2300
passed: 1
failed: 1
skipped: 0
error: null
tested_embed_ids[2]: code-1,app-1
revisions[1]{path,revision}:
  web-app/a.py,r1
tests[2]{name,status,duration_ms,error}:
  adds,passed,5,null
  \"removes\",failed,7,boom
steps[0]:
evidence[0]:
is_current: true
stale_reason: null
";

const BROWSER: &str = "kind: browser
target: e2b
run_status: passed
exit_code: 0
duration_ms: 9000
passed: 1
failed: 0
skipped: 0
preview_step_index: 1
revisions[0]:
tests[0]:
steps[2]{name,start_ms,end_ms,status,error,is_preview,command,output}:
  Open page,0,500,passed,null,false,null,null
  Click add,500,1400,passed,null,true,null,null
evidence[2]{kind,path,mime_type,size_bytes,asset_id,at_step}:
  video,outputs/test-run/video.webm,video/webm,100,asset-v,null
  preview_frame,outputs/test-run/preview.png,image/png,50,asset-p,1
is_current: false
stale_reason: revisions_changed
";

const CLI: &str = "kind: cli
target: remote_source
run_status: passed
exit_code: 0
duration_ms: 1200
passed: 1
failed: 0
skipped: 0
revisions[0]:
tests[0]:
steps[2]{name,start_ms,end_ms,status,error,is_preview,command,output}:
  add,0,5,passed,null,false,recipes add Pancakes,\"Added\\nPancakes\"
  list,5,9,failed,null,false,recipes list,\"1 recipe\"
evidence[1]{kind,path,mime_type,size_bytes,asset_id,at_step}:
  terminal_cast,outputs/test-run/terminal.cast,application/x-asciicast,9,cast-1,null
";

#[test]
fn unit_result_decodes_to_summary_layout_with_failed_tests_first() {
    let embed = TestResultEmbed::decode_toon(UNIT).unwrap();
    assert_eq!(embed.kind, RunKind::Unit);
    assert_eq!(embed.tested_embed_ids, vec!["code-1", "app-1"]);
    assert_eq!(embed.revisions[0].revision, "r1");
    let view = embed.render_model();
    assert_eq!(view.headline, "Unit tests failed");
    assert_eq!(view.counts, "1 passed, 1 failed, 0 skipped in 2.3s");
    assert_eq!(view.layout, Layout::Summary);
    assert_eq!(view.tests[0].name, "removes");
    assert!(view.render_full().contains("[FAIL] removes\n      boom"));
}

#[test]
fn browser_result_renders_timeline_video_preview_and_stale_marker() {
    let embed = TestResultEmbed::decode_toon(BROWSER).unwrap();
    let view = embed.render_model();
    assert!(!view.is_current);
    let Layout::Timeline {
        steps,
        video,
        preview,
    } = &view.layout
    else {
        panic!("timeline")
    };
    assert_eq!(
        steps.iter().map(|s| s.name.as_str()).collect::<Vec<_>>(),
        ["Open page", "Click add"]
    );
    assert!(steps[1].is_preview && !steps[0].is_preview);
    assert_eq!(steps[1].duration_ms, 900);
    assert_eq!(video.as_ref().unwrap().asset_id.as_deref(), Some("asset-v"));
    assert_eq!(
        preview.as_ref().unwrap().path,
        "outputs/test-run/preview.png"
    );
    let text = view.render_full();
    assert!(text.contains("[stale: files changed"));
    assert!(text.contains("Video: outputs/test-run/video.webm (asset asset-v)"));
    assert!(text.contains("  2. [PASS] Click add at 0.5s, 0.9s (preview)"));
}

#[test]
fn cli_result_renders_terminal_steps_with_command_output_status_and_cast() {
    let embed = TestResultEmbed::decode_toon(CLI).unwrap();
    let view = embed.render_model();
    let Layout::Terminal { steps, cast } = &view.layout else {
        panic!("terminal")
    };
    assert_eq!(steps[0].command, "recipes add Pancakes");
    assert_eq!(steps[0].output, "Added\nPancakes");
    assert_eq!(steps[1].status, StepStatus::Failed);
    assert_eq!(cast.as_ref().unwrap().asset_id.as_deref(), Some("cast-1"));
    let text = view.render_full();
    assert!(text.contains("$ recipes add Pancakes\n  Added\n  Pancakes\n[PASS] step 1"));
    assert!(text.contains("Cast: outputs/test-run/terminal.cast (asset cast-1)"));
    assert!(embed.is_current, "missing is_current defaults to current");
}

#[test]
fn decode_content_accepts_json_and_rejects_wrong_shape() {
    let json = r#"{"kind":"unit","target":"e2b","run_status":"passed","tested_embed_ids":"a|b"}"#;
    assert_eq!(
        TestResultEmbed::decode_content(json)
            .unwrap()
            .tested_embed_ids,
        vec!["a", "b"]
    );
    let error = TestResultEmbed::decode_content("kind: load\n").unwrap_err();
    assert_eq!(error.code(), "test_result_invalid");
}
