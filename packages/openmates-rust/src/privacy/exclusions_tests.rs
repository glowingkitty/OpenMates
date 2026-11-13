//! Composer exclusions keep un-redacted spans in clear while others are replaced.
use super::*;
use zeroize::Zeroizing;

fn excluding(originals: &[&str], placeholders: &[&str]) -> PiiExclusions {
    PiiExclusions {
        originals: originals
            .iter()
            .map(|v| Zeroizing::new((*v).to_owned()))
            .collect(),
        placeholders: placeholders.iter().map(|v| (*v).to_owned()).collect(),
    }
}

#[test]
fn excluded_original_stays_in_clear_while_other_detections_are_replaced() {
    let text = "Write to alice@example.org and bob@example.org today";
    let prepared =
        prepare_excluding(text, &[], &[], &excluding(&["alice@example.org"], &[])).unwrap();
    assert!(prepared.text.contains("alice@example.org"));
    assert!(!prepared.text.contains("bob@example.org"));
    assert_eq!(prepared.mappings.len(), 1);
    assert_eq!(prepared.mappings[0]["original"], "bob@example.org");
    let all = prepare(text, &[], &[]).unwrap();
    assert!(!all.text.contains("alice@example.org"));
}

#[test]
fn excluded_known_mapping_is_not_reapplied_but_keeps_restoring_history() {
    let known = vec![
        json!({"original":"Example Street 1","placeholder":"[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]","type":"ADDRESS"}),
    ];
    let text = "Meet at Example Street 1";
    let kept = prepare_excluding(
        text,
        &[],
        &known,
        &excluding(&[], &["[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]"]),
    )
    .unwrap();
    assert_eq!(kept.text, text);
    assert_eq!(kept.mappings, known);
    let by_original =
        prepare_excluding(text, &[], &known, &excluding(&["Example Street 1"], &[])).unwrap();
    assert_eq!(by_original.text, text);
    let replaced = prepare(text, &[], &known).unwrap();
    assert_eq!(
        replaced.text,
        "Meet at [OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]"
    );
}

#[test]
fn exclusion_validation_rejects_empty_oversized_and_non_token_entries() {
    assert!(excluding(&["alice@example.org"], &[]).validate().is_ok());
    assert!(matches!(
        excluding(&[""], &[]).validate(),
        Err(Error::Invalid(_))
    ));
    let long = "x".repeat(MAX_PII_EXCLUSION_BYTES + 1);
    assert!(matches!(
        excluding(&[&long], &[]).validate(),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        excluding(&[], &["not-a-token"]).validate(),
        Err(Error::Invalid(_))
    ));
    let many: Vec<&str> = vec!["a"; MAX_PII_EXCLUSIONS + 1];
    assert!(matches!(
        excluding(&many, &[]).validate(),
        Err(Error::Invalid(_))
    ));
    assert_eq!(
        format!("{:?}", excluding(&["alice@example.org"], &[])),
        "PiiExclusions { originals: 1, placeholders: 0 }"
    );
}
