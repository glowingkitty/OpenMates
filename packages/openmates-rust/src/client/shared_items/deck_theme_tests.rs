//! Deck kind and theme: markup round trip, CRDT survival and convergence, and the
//! `set_theme` operation (validation, one undo step).

use super::deck::DeckDocument;
use super::deck_error::DeckError;
use super::deck_markup::{parse_deck_markup, serialise_deck_markup};
use super::deck_operations::{DeckOperation, DeckOutcome};
use super::deck_theme::{DeckKind, DeckTheme};

const THEMED_DECK: &str = r##"<deck title="Club" aspect="16:9" template="builtin:plain">
  <theme heading="Trebuchet MS" body="Verdana" background="#f4faf5" foreground="#12301c" accent="#1f9d55" accent-2="#f2c94c" muted="#5b7a65" surface="#fff"/>
  <slide id="s1" layout="title">
    <text id="e1" x="80" y="60" w="1200" h="120" role="title">Hello</text>
  </slide>
</deck>
"##;

const TEMPLATE: &str = r##"<deck title="Club Green" aspect="16:9" template="builtin:plain" kind="template">
  <theme heading="Trebuchet MS" body="Verdana" background="#f4faf5" foreground="#12301c" accent="#1f9d55" accent-2="#f2c94c" muted="#5b7a65" surface="#ffffff"/>
  <slide id="s1" layout="title">
  </slide>
</deck>
"##;

const PARTIAL: &str = r##"<deck title="" aspect="4:3" template="library:t1" kind="template">
  <theme accent="#abc" muted="#5b7a65"/>
  <slide id="s1">
  </slide>
</deck>
"##;

fn theme(accent: &str) -> DeckTheme {
    DeckTheme {
        accent: Some(accent.to_string()),
        heading: Some("georgia".to_string()),
        ..DeckTheme::default()
    }
}

// contract-test: supporting surface=sdks.rust assertions=slides.templates.library
#[test]
fn themed_decks_and_templates_round_trip_byte_for_byte() {
    for markup in [THEMED_DECK, TEMPLATE, PARTIAL] {
        let model = parse_deck_markup(markup).expect("parses");
        assert_eq!(serialise_deck_markup(&model), markup);
        let deck = DeckDocument::from_markup(markup, 1).expect("hydrates");
        assert_eq!(deck.to_markup().expect("serialises"), markup);
    }
    let template = parse_deck_markup(TEMPLATE).expect("parses");
    assert_eq!(template.kind, DeckKind::Template);
    let partial = parse_deck_markup(PARTIAL)
        .expect("parses")
        .theme
        .expect("theme");
    assert_eq!(partial.accent.as_deref(), Some("#abc"));
    assert_eq!(partial.heading, None);
    let plain = parse_deck_markup(THEMED_DECK).expect("parses");
    assert_eq!(plain.kind, DeckKind::Deck);
    assert_eq!(
        plain.theme.expect("theme").accent_2.as_deref(),
        Some("#f2c94c")
    );
}

// contract-test: supporting surface=sdks.rust assertions=slides.templates.library
#[test]
fn non_canonical_theme_markup_is_refused() {
    for bad in [
        THEMED_DECK.replace("#f4faf5", "#F4FAF5"),
        THEMED_DECK.replace("Verdana", "Comic Sans"),
        THEMED_DECK.replace("\"#fff\"", "\"#ffff\""),
        PARTIAL
            .replace(" muted=\"#5b7a65\"", "")
            .replace("accent=\"#abc\"", ""),
        PARTIAL.replace("kind=\"template\"", "kind=\"deck\""),
        THEMED_DECK.replace("  <theme", "  <theme foo=\"1\""),
    ] {
        assert!(
            matches!(
                parse_deck_markup(&bad),
                Err(DeckError::MarkupNotNormalised { .. })
            ),
            "{bad}"
        );
    }
}

// contract-test: supporting surface=sdks.rust assertions=slides.templates.library
#[test]
fn kind_and_theme_converge_between_replicas() {
    let mut a = DeckDocument::from_markup(TEMPLATE, 1).expect("hydrates");
    let mut b = DeckDocument::from_update(&a.encode_state(), 2).expect("valid state");
    assert_eq!(b.to_markup().expect("synced"), TEMPLATE);
    a.apply(DeckOperation::SetTheme {
        template: "library:x".into(),
        theme: Some(theme("#112233")),
    })
    .expect("applies");
    b.apply(DeckOperation::SetTheme {
        template: "library:y".into(),
        theme: Some(theme("#445566")),
    })
    .expect("applies");
    let to_b = a.encode_update_since(&b.state_vector()).expect("vector");
    let to_a = b.encode_update_since(&a.state_vector()).expect("vector");
    b.apply_update(&to_b).expect("applies");
    a.apply_update(&to_a).expect("applies");
    assert_eq!(a.to_markup().expect("a"), b.to_markup().expect("b"));
    assert_eq!(a.view().kind, DeckKind::Template);
}

// contract-test: supporting surface=sdks.rust assertions=slides.templates.library
#[test]
fn set_theme_replaces_template_and_theme_in_one_undo_step() {
    let mut deck = DeckDocument::from_markup(THEMED_DECK, 1).expect("hydrates");
    let slides_before = deck.model().slides;
    let outcome = deck
        .apply(DeckOperation::SetTheme {
            template: "library:club".into(),
            theme: Some(theme("#ABCDEF")),
        })
        .expect("applies");
    assert_eq!(outcome, DeckOutcome::Applied);
    let view = deck.view();
    assert_eq!(view.template, "library:club");
    let applied = view.theme.expect("theme");
    assert_eq!(applied.accent.as_deref(), Some("#abcdef"));
    assert_eq!(applied.heading.as_deref(), Some("Georgia"));
    assert_eq!(applied.background, None, "old theme values are replaced");
    assert_eq!(deck.model().slides, slides_before);
    assert!(deck.undo());
    assert_eq!(deck.to_markup().expect("serialises"), THEMED_DECK);
    assert!(deck.redo());
    assert_eq!(deck.view().template, "library:club");
    let same = deck
        .apply(DeckOperation::SetTheme {
            template: "library:club".into(),
            theme: Some(theme("#abcdef")),
        })
        .expect("applies");
    assert_eq!(same, DeckOutcome::Unchanged);
    deck.apply(DeckOperation::SetTheme {
        template: "builtin:plain".into(),
        theme: None,
    })
    .expect("applies");
    assert_eq!(deck.view().theme, None);
}

// contract-test: supporting surface=sdks.rust assertions=slides.templates.library
#[test]
fn set_theme_refuses_invalid_template_and_values() {
    let mut deck = DeckDocument::from_markup(THEMED_DECK, 1).expect("hydrates");
    let bad_template = DeckOperation::SetTheme {
        template: "https://x".into(),
        theme: None,
    };
    let bad_colour = DeckOperation::SetTheme {
        template: "builtin:plain".into(),
        theme: Some(theme("red")),
    };
    let bad_font = DeckOperation::SetTheme {
        template: "builtin:plain".into(),
        theme: Some(DeckTheme {
            body: Some("Comic Sans".into()),
            ..DeckTheme::default()
        }),
    };
    for op in [bad_template, bad_colour, bad_font] {
        assert!(matches!(
            deck.apply(op),
            Err(DeckError::InvalidValue { .. })
        ));
    }
    assert_eq!(deck.to_markup().expect("serialises"), THEMED_DECK);
    assert!(!deck.can_undo());
}
