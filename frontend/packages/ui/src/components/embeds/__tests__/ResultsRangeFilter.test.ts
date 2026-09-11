// @vitest-environment jsdom
import { mount, tick, unmount } from "svelte";
import { describe, expect, it, vi } from "vitest";
import ResultsRangeFilter from "../ResultsRangeFilter.svelte";

describe("ResultsRangeFilter pointer interaction", () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it("captures continuous dragging of either handle and releases it on cancellation", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);
    const onChange = vi.fn();
    const component = mount(ResultsRangeFilter, {
      target,
      props: { min: 360, max: 780, lower: 360, upper: 780, values: [360, 480, 780], step: 5,
        label: "Time", testId: "time", formatValue: String, onChange },
    });
    await tick();
    const rail = target.querySelector<HTMLDivElement>(".range-controls")!;
    rail.getBoundingClientRect = () => ({ left: 0, width: 448 } as DOMRect);
    rail.setPointerCapture = vi.fn();
    rail.hasPointerCapture = () => true;
    rail.releasePointerCapture = vi.fn();
    const pointer = (type: string, x: number, pointerId = 1) => {
      const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, button: 0 });
      Object.defineProperties(event, { pointerId: { value: pointerId }, isPrimary: { value: true } });
      rail.dispatchEvent(event);
    };
    pointer("pointerdown", 14);
    pointer("pointermove", 119);
    expect(onChange).toHaveBeenLastCalledWith("min", 465);
    pointer("pointermove", 224);
    expect(onChange).toHaveBeenLastCalledWith("min", 570);
    expect(document.activeElement).toBe(target.querySelector(".lower"));
    pointer("pointerup", 224);
    expect(rail.releasePointerCapture).toHaveBeenCalledWith(1);

    pointer("pointerdown", 434);
    pointer("pointermove", 329);
    expect(onChange).toHaveBeenLastCalledWith("max", 675);
    expect(document.activeElement).toBe(target.querySelector(".upper"));
    pointer("pointermove", 224, 2);
    expect(onChange).toHaveBeenLastCalledWith("max", 675);
    pointer("pointercancel", 329);
    const callsAfterCancel = onChange.mock.calls.length;
    pointer("pointermove", 14);
    expect(onChange).toHaveBeenCalledTimes(callsAfterCancel);

    // Keyboard input remains native and uses the same change callback.
    const minimum = target.querySelector<HTMLInputElement>(".lower")!;
    minimum.value = "400";
    minimum.dispatchEvent(new Event("input", { bubbles: true }));
    expect(onChange).toHaveBeenLastCalledWith("min", 400);
    await unmount(component);
    target.remove();
  });
});
