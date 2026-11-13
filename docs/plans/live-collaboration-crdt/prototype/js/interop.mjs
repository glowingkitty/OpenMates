// Yjs (JS) side of the spike's wire-compatibility check, run by tests/interop.rs.
// Reads a yrs-made v1 state, prints what Yjs sees, makes a main-thread-style edit
// (emoji to exercise UTF-16 offsets, a cell, a slide property) and writes the update.
import * as Y from "yjs";
import { readFileSync, writeFileSync } from "node:fs";

const [inPath, outPath] = process.argv.slice(2);
const doc = new Y.Doc();
Y.applyUpdate(doc, readFileSync(inPath), "rust-core");
const sv = Y.encodeStateVector(doc);

const frag = doc.getXmlFragment("default");
const cells = doc.getMap("cells");
const slides = doc.getMap("slides");
const seen = {
  doc: frag.toString(),
  cells: cells.toJSON(),
  order: doc.getArray("slide_order").toJSON(),
};

doc.transact(() => {
  const para = frag.get(1).get(0); // Y.XmlText of the paragraph
  para.insert(0, "🙂 ");
  para.insert(para.length - 1, "!", { italic: {} });
  cells.set("r1:c2", "=r1c1*2");
  slides.get("s1").get("elements").get("e1").set("y", 640);
}, "tiptap");

writeFileSync(outPath, Y.encodeStateAsUpdate(doc, sv));
process.stdout.write(JSON.stringify(seen));
