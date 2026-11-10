//! Size probe: exercises the API surface the editors need (rich text with marks, maps,
//! lists, undo, update encode/apply) so the linker keeps a realistic share of each engine.
//! Not product code; see ../../spike.md for the numbers.

/// Reserves `len` bytes the host fills with an incoming update before calling `run`.
#[no_mangle]
pub extern "C" fn alloc(len: usize) -> *mut u8 {
    let mut v = vec![0u8; len];
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

fn input<'a>(ptr: *const u8, len: usize) -> &'a [u8] {
    // SAFETY: the host passes a pointer returned by `alloc(len)` that it filled.
    unsafe { std::slice::from_raw_parts(ptr, len) }
}

#[cfg(feature = "yrs")]
#[no_mangle]
pub extern "C" fn run(ptr: *const u8, len: usize) -> usize {
    use std::sync::Arc;
    use yrs::updates::decoder::Decode;
    use yrs::{
        Any, Array, Doc, GetString, Map, OffsetKind, Options, Text, Transact, Update,
        XmlElementPrelim, XmlFragment, XmlTextPrelim,
    };
    let mut o = Options::with_client_id(yrs::block::ClientID::new(7));
    o.offset_kind = OffsetKind::Utf16;
    let doc = Doc::with_options(o);
    let frag = doc.get_or_insert_xml_fragment("default");
    let cells = doc.get_or_insert_map("cells");
    let order = doc.get_or_insert_array("order");
    // On wasm32-unknown-unknown yrs has no system clock; the core would pass Date.now().
    let opts = yrs::undo::Options {
        capture_timeout_millis: 500,
        tracked_origins: Default::default(),
        capture_transaction: None,
        timestamp: Arc::new(|| 0u64),
        init_undo_stack: vec![],
        init_redo_stack: vec![],
    };
    let mut um: yrs::undo::UndoManager<()> = yrs::undo::UndoManager::with_options(opts);
    um.expand_scope(&doc, &frag);
    let mut txn = doc.transact_mut();
    if let Ok(u) = Update::decode_v1(input(ptr, len)) {
        let _ = txn.apply_update(u);
    }
    let el = XmlFragment::insert(&frag, &mut txn, 0, XmlElementPrelim::empty("paragraph"));
    let t = XmlFragment::insert(&el, &mut txn, 0, XmlTextPrelim::new("hello"));
    t.format(
        &mut txn,
        0,
        2,
        yrs::types::Attrs::from([("bold".into(), Any::Bool(true))]),
    );
    Map::insert(&cells, &mut txn, "a", "1");
    Array::insert(&order, &mut txn, 0, "s1");
    let out = txn.encode_update_v1();
    drop(txn);
    um.undo_blocking();
    let shown = frag.get_string(&doc.transact()).len();
    out.len() + shown
}

#[cfg(feature = "loro")]
#[no_mangle]
pub extern "C" fn run(ptr: *const u8, len: usize) -> usize {
    use loro::{ExportMode, LoroDoc, UndoManager};
    let doc = LoroDoc::new();
    let _ = doc.import(input(ptr, len));
    let text = doc.get_text("default");
    let _ = text.insert(0, "hello");
    let _ = text.mark(0..2, "bold", true);
    let _ = doc.get_map("cells").insert("a", "1");
    let order = doc.get_movable_list("order");
    let _ = order.insert(0, "s1");
    let _ = order.mov(0, 0);
    let _ = doc.get_tree("tree").create(None);
    let mut um = UndoManager::new(&doc);
    doc.commit();
    let _ = um.undo();
    let out = doc
        .export(ExportMode::all_updates())
        .map(|v| v.len())
        .unwrap_or(0);
    out + text.to_string().len()
}

#[cfg(feature = "none")]
#[no_mangle]
pub extern "C" fn run(ptr: *const u8, len: usize) -> usize {
    input(ptr, len).iter().map(|b| *b as usize).sum()
}
