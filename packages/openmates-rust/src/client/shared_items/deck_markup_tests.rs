//! Normalised slides markup round trip (every element kind, all three aspects) and refusal of non-normalised input.

use super::deck::DeckDocument;
use super::deck_error::DeckError;
use super::deck_markup::{ElementContent, parse_deck_markup, serialise_deck_markup};
use super::deck_values::{DeckAspect, ElementKind};

// Each fixture is a fixed point of `normalise_slides_markup` (checked with the backend
// normaliser when the fixture was written): normalising it returns it byte for byte.

/// 16:9 deck using every element kind, escaping in attributes, text, items and notes,
/// a multi-line block and an empty slide.
pub(super) const FULL_DECK: &str = r##"<deck title="Q3 &amp; &quot;results&quot; &#x27;26" aspect="16:9" template="builtin:plain">
  <slide id="s1" layout="title-and-content" transition="fade">
    <text id="e1" x="80" y="60" w="1200" h="120" role="title" font="Georgia" size="64" color="#ff8800" align="center" weight="bold" animate="fade" step="1">Q3 <b>results</b> &amp; <i>more</i><br/><ul><li>one</li><li>two &lt;3</li></ul></text>
    <image id="e2" x="1000" y="220" w="800" h="500" src="embed:revenue-chart" alt="Revenue chart" fit="cover"/>
    <video id="e3" x="80" y="220" w="860" h="484" src="youtube:abc123"/>
    <shape id="e4" x="0" y="1000" w="1920" h="80" kind="rect" fill="accent" stroke="#000"/>
    <notepad id="e5" x="80" y="740" w="860" h="260" title="Ideas"/>
    <todo id="e6" x="1000" y="760" w="800" h="240" title="Next"><item done="false">Book venue</item><item done="true">Send &lt;invite&gt;</item></todo>
    <link id="e7" href="https://example.com/a?b=1">Source</link>
    <block id="e8" x="1000" y="760" w="800" h="240" title="Demo"><div class="x">
  <script>let a = 1 < 2;</script>
</div></block>
    <notes>Speaker notes
second line &amp; more.</notes>
  </slide>
  <slide id="s2">
  </slide>
</deck>
"##;

/// 16:10 deck with custom ids, a library template and a box touching the canvas bottom.
pub(super) const LAPTOP_DECK: &str = r##"<deck title="" aspect="16:10" template="library:team-deck">
  <slide id="intro" layout="title">
    <text id="headline" x="0" y="1100" w="1920" h="100">Wide <u>and</u> <s>tall</s></text>
    <video id="clip" x="10" y="10" w="640" h="360" src="vimeo:123456" alt="Clip"/>
  </slide>
</deck>
"##;

/// 4:3 deck with a box in the last canvas pixel, an element without geometry, an empty
/// to-do list and notes only.
pub(super) const CLASSIC_DECK: &str = r##"<deck title="Classic" aspect="4:3" template="builtin:plain">
  <slide id="s1" transition="slide">
    <shape id="e1" x="1919" y="1439" w="1" h="1" kind="ellipse"/>
    <image id="e2" src="embed:a.b_c-d"/>
    <todo id="e3"></todo>
    <notes>Only notes.</notes>
  </slide>
</deck>
"##;

/// Notepad bodies (escaped text, newline) and the `hidden` attribute (after `title`,
/// before `animate`). Python and Rust share this exact string: the Python test
/// `test_notepad_body_and_hidden_fixture_is_a_fixed_point` normalises it unchanged.
pub(super) const NOTEPAD_DECK: &str = r##"<deck title="Notes" aspect="16:9" template="builtin:plain">
  <slide id="s1">
    <notepad id="e1" x="80" y="740" w="860" h="260" title="Ideas" hidden="true" animate="fade">Line one &amp; &lt;b&gt;
Line two</notepad>
    <todo id="e2" title="Next" hidden="true"><item done="true">A</item></todo>
    <notepad id="e3"/>
  </slide>
</deck>
"##;

// contract-test: supporting surface=sdks.rust assertions=slides.format.positioned-elements,live-collab.core.one-shared-model
#[test]
fn normalised_markup_round_trips_byte_for_byte_for_every_element_kind_and_aspect() {
    for (fixture, aspect) in [
        (FULL_DECK, DeckAspect::Wide),
        (LAPTOP_DECK, DeckAspect::Laptop),
        (CLASSIC_DECK, DeckAspect::Classic),
        (NOTEPAD_DECK, DeckAspect::Wide),
    ] {
        let model = parse_deck_markup(fixture).expect("fixture is normalised");
        assert_eq!(model.aspect, aspect);
        assert_eq!(serialise_deck_markup(&model), fixture);
        // Through the yrs replica as well: hydrate, then save.
        let deck = DeckDocument::from_markup(fixture, 1).expect("hydrates");
        assert_eq!(deck.to_markup().expect("has slides"), fixture);
        assert_eq!(deck.model(), model);
    }
}

#[test]
fn parsed_model_exposes_kinds_geometry_and_content() {
    let model = parse_deck_markup(FULL_DECK).expect("fixture is normalised");
    assert_eq!(model.title, "Q3 & \"results\" '26");
    let slide = &model.slides[0];
    let kinds: Vec<ElementKind> = slide.elements.iter().map(|e| e.kind).collect();
    assert_eq!(
        kinds,
        [
            ElementKind::Text,
            ElementKind::Image,
            ElementKind::Video,
            ElementKind::Shape,
            ElementKind::Notepad,
            ElementKind::Todo,
            ElementKind::Link,
            ElementKind::Block,
        ]
    );
    let text = &slide.elements[0];
    assert_eq!(
        (text.x, text.y, text.w, text.h),
        (Some(80), Some(60), Some(1200), Some(120))
    );
    assert_eq!(
        text.attributes.get("font").map(String::as_str),
        Some("Georgia")
    );
    assert!(
        matches!(&slide.elements[5].content, ElementContent::Items(items) if items.len() == 2 && items[1].done && items[1].text == "Send <invite>")
    );
    assert_eq!(slide.notes, "Speaker notes\nsecond line & more.");
    assert!(model.slides[1].elements.is_empty());
}

fn refused(markup: &str) -> DeckError {
    parse_deck_markup(markup).expect_err("not normalised")
}

#[test]
fn refuses_markup_that_is_not_normaliser_output() {
    let wrap = |slide_body: &str| {
        format!(
            "<deck title=\"\" aspect=\"16:9\" template=\"builtin:plain\">\n  <slide id=\"s1\">\n{slide_body}  </slide>\n</deck>\n"
        )
    };
    let cases = [
        // No <deck> wrapper (the normaliser accepts it as input but never writes it).
        "<slide id=\"s1\">\n</slide>\n".to_string(),
        wrap("    <script>alert(1)</script>\n"),
        wrap("    <text id=\"e1\" onclick=\"x\">Hi</text>\n"),
        wrap("    <text id=\"e1\"><span>Hi</span></text>\n"),
        // Attribute order differs from the normaliser's.
        wrap("    <text id=\"e1\" role=\"title\" x=\"1\">Hi</text>\n"),
        // Box outside the 1080-high canvas.
        wrap("    <shape id=\"e1\" y=\"1000\" h=\"200\"/>\n"),
        // Unknown character reference and an empty notes line.
        wrap("    <link id=\"e1\" href=\"https://a.example\">&copy;</link>\n"),
        wrap("    <notes></notes>\n"),
        // External image and a duplicate id.
        wrap("    <image id=\"e1\" src=\"https://evil.example/x.png\"/>\n"),
        wrap("    <shape id=\"s1\"/>\n"),
        wrap("    <block id=\"e1\">a</BLOCK >b</block>\n"),
    ];
    for case in cases {
        let error = refused(&case);
        assert_eq!(error.code(), "slides_markup_not_normalised", "{case}");
    }
}

#[test]
fn a_deck_without_slides_is_refused() {
    let error = refused("<deck title=\"\" aspect=\"16:9\" template=\"builtin:plain\">\n</deck>\n");
    assert_eq!(error, DeckError::NoSlides);
}

#[test]
fn notepad_body_and_hidden_flag_are_parsed() {
    let model = parse_deck_markup(NOTEPAD_DECK).expect("fixture is normalised");
    let elements = &model.slides[0].elements;
    assert_eq!(
        elements[0].content,
        ElementContent::Plain("Line one & <b>\nLine two".into())
    );
    assert_eq!(
        elements[0].attributes.get("hidden").map(String::as_str),
        Some("true")
    );
    assert!(elements[1].attributes.contains_key("hidden"));
    assert_eq!(elements[2].content, ElementContent::Plain(String::new()));
    assert!(!elements[2].attributes.contains_key("hidden"));
}

#[test]
fn refuses_non_normalised_notepad_bodies_and_hidden_values() {
    let wrap = |body: &str| {
        format!(
            "<deck title=\"\" aspect=\"16:9\" template=\"builtin:plain\">\n  <slide id=\"s1\">\n    {body}\n  </slide>\n</deck>\n"
        )
    };
    for case in [
        wrap("<notepad id=\"e1\"></notepad>"),
        wrap("<notepad id=\"e1\"> padded </notepad>"),
        wrap("<notepad id=\"e1\"><b>x</b></notepad>"),
        wrap("<notepad id=\"e1\" hidden=\"false\"/>"),
        wrap("<notepad id=\"e1\" animate=\"fade\" hidden=\"true\"/>"),
        wrap("<shape id=\"e1\" hidden=\"true\"/>"),
    ] {
        assert_eq!(
            refused(&case).code(),
            "slides_markup_not_normalised",
            "{case}"
        );
    }
}
