//! Canonical Design scene limits and unsafe input rejection.
// contract-test: supporting surface=gui.web assertions=design-editor.view.validated-scene
use super::*;
use serde_json::json;

fn layer() -> Value {
    json!({
        "id":"curve", "kind":"path", "name":"Curve", "x":0, "y":5,
        "width":10, "height":12, "rotation":0, "color":"#eeffee",
        "path":"M 0 0 Q 5 2 10 12 Z", "viewWidth":10, "viewHeight":12
    })
}

fn scene() -> Value {
    json!({
        "schemaVersion":1, "title":"Studio floor plan",
        "pages":[{"id":"main","name":"Main", "width":640,"height":640,
            "background":"#ffffee", "layers":[layer()]}]
    })
}

#[test]
fn accepts_a_bounded_scene_in_page_order() {
    let value = scene();
    let decoded = decode(&value.to_string()).unwrap();
    assert_eq!(*decoded, value);
}

#[test]
fn refuses_the_251st_layer_and_duplicate_layer_ids() {
    let mut value = scene();
    let mut layers: Vec<_> = (0..250)
        .map(|i| {
            let mut layer = layer();
            layer["id"] = json!(format!("path-{i}"));
            layer
        })
        .collect();
    value["pages"][0]["layers"] = json!(layers);
    assert!(decode(&value.to_string()).is_ok());
    layers.push(layer());
    value["pages"][0]["layers"] = json!(layers);
    assert!(decode(&value.to_string()).is_err());
    value["pages"][0]["layers"] = json!([layer(), layer()]);
    assert!(decode(&value.to_string()).is_err());
}

#[test]
fn refuses_unsupported_version_remote_images_and_invalid_vectors() {
    let mut value = scene();
    for path in ["M 1", "M 0 0 Z !", "M 9.9e+99 0", "M 0 NaN", "<svg/>"] {
        value["pages"][0]["layers"][0]["path"] = json!(path);
        assert!(decode(&value.to_string()).is_err(), "{path}");
    }
    value["schemaVersion"] = json!(2);
    assert!(matches!(
        decode(&value.to_string()),
        Err(Error::Invalid("Unsupported Design scene version."))
    ));
    value = scene();
    let target = value["pages"][0]["layers"][0].as_object_mut().unwrap();
    target.retain(|key, _| !["color", "path", "viewWidth", "viewHeight"].contains(&key.as_str()));
    target.insert("kind".into(), json!("image"));
    target.insert("assetId".into(), json!("https://example.org/image"));
    assert!(decode(&value.to_string()).is_err());
    value["pages"][0]["layers"][0]["assetId"] = json!("00112233-4455-4677-8899-aabbccddeeff");
    assert!(decode(&value.to_string()).is_ok());
}

#[test]
fn selects_only_one_top_level_design_attachment() {
    let id = "00112233-4455-4677-8899-aabbccddeeff";
    let block = format!(
        "```json\n{{\"type\":\"design-document\",\"embed_id\":\"{id}\",\"reference_only\":true}}\n```"
    );
    let reference =
        turn_reference(&format!("Change the caption.\n\n{block}")).expect("single attachment");
    assert_eq!(reference["embedId"], id);
    assert_eq!(
        reference["text"].as_str().unwrap().trim(),
        "Change the caption."
    );
    assert!(turn_reference(&format!("{block}\n\n{block}")).is_none());
    assert!(turn_reference(&format!("````markdown\n{block}\n````")).is_none());
}

#[test]
fn validates_the_source_and_keeps_proposals_out_of_new_revisions() {
    let id = "00112233-4455-4677-8899-aabbccddeeff";
    let mut original = scene();
    let source = source_context(&original.to_string(), id, 3).unwrap();
    assert_eq!(source["base_version"], 3);
    assert_eq!(source["scene"], original);
    assert!(source_context(&original.to_string(), id, 0).is_err());
    original["proposal"] = json!({"embedId": id, "baseVersion": 3});
    assert!(decode(&original.to_string()).is_ok());
    assert!(source_context(&original.to_string(), id, 3).is_err());
}
