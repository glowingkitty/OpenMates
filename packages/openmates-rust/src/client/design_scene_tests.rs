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
