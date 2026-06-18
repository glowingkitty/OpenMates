// frontend/packages/ui/src/demo_chats/data/example_chats/__tests__/usb-c-3v3-ldo-pcb-schematic.test.ts
//
// Regression coverage for the Electronics PCB schematic example chat.
// The settings content page discovers example chats through
// metadata.content_embed_examples, so this test protects the catalog link.

import { describe, expect, it } from "vitest";

import { CONTENT_EMBED_CATALOG } from "../../../../data/embedRegistry.generated";
import { usbC3v3LdoPcbSchematicChat } from "../usb-c-3v3-ldo-pcb-schematic";

describe("USB-C 3.3V LDO PCB schematic example chat", () => {
  it("links the Electronics schematic content catalog entry to a PCB schematic embed", () => {
    const catalogEntry = CONTENT_EMBED_CATALOG.find(
      (entry) => entry.id === "electronics.schematic",
    );

    expect(catalogEntry).toMatchObject({
      appId: "electronics",
      contentTypeId: "schematic",
      frontendType: "electronics-pcb-schematic",
      exampleKey: "electronics.schematic",
    });
    expect(
      usbC3v3LdoPcbSchematicChat.metadata?.content_embed_examples,
    ).toContain("electronics.schematic");
    expect(usbC3v3LdoPcbSchematicChat.embeds).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "pcb_schematic",
        }),
      ]),
    );
  });
});
