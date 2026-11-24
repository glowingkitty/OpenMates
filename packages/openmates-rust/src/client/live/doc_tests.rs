//! Document adapter: HTML subset round trip, raw preservation, mirror convergence.

use super::doc_html::{Block, parse_blocks};
use super::support::*;
use super::{LiveItem, LiveItemKind};
use yrs::updates::decoder::Decode;
use yrs::{Doc, ReadTxn, Text, Transact, Update, XmlFragment, XmlOut};

pub(super) const DOC: &str = concat!(
    "<h1>Title</h1>",
    "<p>Hello <strong>bold</strong> and <em>it</em> and <code>x</code> and ",
    "<a href=\"https://example.org/a?b=1&amp;c=2\"><strong>link</strong></a> &lt;ok&gt;</p>",
    "<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul>",
    "<ol><li><p>a</p><p>b</p></li></ol>",
    "<blockquote>quoted <u>x</u></blockquote>",
    "<p>kept <u>raw</u></p>",
    "<ol><li>x <u>y</u></li></ol>",
    "<p></p>",
);

#[test]
fn html_subset_round_trips_through_the_yjs_fragment() {
    assert_eq!(create(LiveItemKind::Doc, DOC).text_form().unwrap(), DOC);
}

#[test]
fn unsupported_nodes_are_preserved_as_raw_blocks() {
    let blocks = parse_blocks(DOC);
    assert!(blocks.contains(&Block::Raw(
        "<blockquote>quoted <u>x</u></blockquote>".into()
    )));
    assert!(blocks.contains(&Block::Raw("<p>kept <u>raw</u></p>".into())));
    let table = "<table><tr><td>1</td></tr></table><p>after &nbsp;</p>";
    assert_eq!(create(LiveItemKind::Doc, table).text_form().unwrap(), table);
}

/// A JS-mirror stand-in: a plain Yjs doc that starts from the core's state.
struct Mirror {
    doc: Doc,
}

impl Mirror {
    fn of(item: &LiveItem) -> Self {
        let doc = Doc::new();
        let _ = doc.get_or_insert_xml_fragment("default");
        let state = item.encode_update_since(&[0]).unwrap();
        doc.transact_mut()
            .apply_update(Update::decode_v1(&state).unwrap())
            .unwrap();
        Self { doc }
    }

    /// Inserts `text` at `offset` of the `block`-th top-level paragraph; returns the update.
    fn insert(&self, block: u32, offset: u32, text: &str) -> Vec<u8> {
        let fragment = self.doc.get_or_insert_xml_fragment("default");
        let before = self.doc.transact().state_vector();
        let mut txn = self.doc.transact_mut();
        let Some(XmlOut::Element(p)) = fragment.get(&txn, block) else {
            panic!("no block")
        };
        let Some(XmlOut::Text(t)) = p.get(&txn, 0) else {
            panic!("no text")
        };
        t.insert(&mut txn, offset, text);
        drop(txn);
        self.doc.transact().encode_diff_v1(&before)
    }
}

#[test]
fn concurrent_mirror_inserts_at_different_places_are_both_kept() {
    let mut items = replicas(LiveItemKind::Doc, "<p>alpha</p><p>omega</p>", 2);
    let (m0, m1) = (Mirror::of(&items[0]), Mirror::of(&items[1]));
    let u0 = m0.insert(0, 0, "X");
    let u1 = m1.insert(1, 5, "Y");
    items[0].apply_mirror_update(&u0).unwrap();
    items[1].apply_mirror_update(&u1).unwrap();
    exchange(&mut items, reversed);
    assert_eq!(assert_converged(&items), "<p>Xalpha</p><p>omegaY</p>");
}

#[test]
fn malformed_mirror_update_is_refused() {
    let mut item = create(LiveItemKind::Doc, "<p>a</p>");
    assert!(item.apply_mirror_update(&[0xff, 0xff, 0xff]).is_err());
}
