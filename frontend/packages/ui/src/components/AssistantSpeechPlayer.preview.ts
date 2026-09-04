/**
 * Interactive preview state for the Figma-defined assistant speech player.
 * Exercises chapter navigation, pending waveform hydration, pause, and close.
 * No network, audio provider, encrypted asset, or persisted chat data is used.
 * Access at: /dev/preview/AssistantSpeechPlayer
 */

import { get, writable } from "svelte/store";
import type { AssistantSpeechPlayerState } from "../services/assistantSpeechController";

const readyWaveform = [32, 58, 82, 44, 72, 96, 54, 76, 38, 68, 88, 48];

function createPreviewController() {
  const player = writable<AssistantSpeechPlayerState>({
    responseId: "preview-response",
    chatId: "preview-chat",
    messageId: "preview-message",
    status: "playing",
    activeSegmentId: "segment-1",
    error: null,
    presentationMode: "replayable_track_queue",
    hasReplayableTracks: true,
    mateName: "Sophia",
    mateCategory: "software_development",
    regions: [
      { segmentId: "segment-0", sequence: 0, start: 0, end: 0.24, status: "ready", active: false, chapter: { kind: "heading", text: "Short answer" }, waveform: readyWaveform },
      { segmentId: "segment-1", sequence: 1, start: 0.24, end: 0.52, status: "ready", active: true, chapter: { kind: "heading", text: "Key considerations" }, waveform: readyWaveform },
      { segmentId: "segment-2", sequence: 2, start: 0.52, end: 0.76, status: "generating", active: false, chapter: { kind: "heading", text: "Optimization" }, waveform: [] },
      { segmentId: "segment-3", sequence: 3, start: 0.76, end: 1, status: "ready", active: false, chapter: { kind: "heading", text: "Implementation" }, waveform: readyWaveform },
    ],
  });

  function updateStatus(status: AssistantSpeechPlayerState["status"]) {
    player.update((state) => ({ ...state, status }));
  }

  async function activateSegment(segmentId: string) {
    let shouldHydrate = false;
    player.update((state) => {
      const target = state.regions.find((region) => region.segmentId === segmentId);
      if (!target) return state;
      shouldHydrate = target.status !== "ready";
      return {
        ...state,
        activeSegmentId: target.segmentId,
        status: target.status === "ready" ? "playing" : "waiting_for_segment",
        regions: state.regions.map((region) => ({ ...region, active: region.segmentId === target.segmentId })),
      };
    });
    if (!shouldHydrate) return;
    window.setTimeout(() => {
      player.update((state) => ({
        ...state,
        status: state.activeSegmentId === segmentId ? "playing" : state.status,
        regions: state.regions.map((region) => region.segmentId === segmentId ? { ...region, status: "ready", waveform: readyWaveform } : region),
      }));
    }, 500);
  }

  async function move(direction: -1 | 1) {
    const state = get(player);
    const replayable = state.regions.filter((region) => region.sequence >= 0);
    const activeIndex = replayable.findIndex((region) => region.segmentId === state.activeSegmentId);
    const target = replayable[activeIndex + direction];
    if (target) await activateSegment(target.segmentId);
  }

  return {
    player,
    pause: () => updateStatus("paused"),
    play: async () => updateStatus("playing"),
    previous: () => move(-1),
    next: () => move(1),
    selectSegment: activateSegment,
    continueAfterUserGesture: async () => updateStatus("playing"),
    close: async () => updateStatus("stopped"),
  };
}

export default {
  controller: createPreviewController(),
  onHeightChange: () => {},
};

export const variants = {
  passiveConfirmation: {
    controller: (() => {
      const controller = createPreviewController();
      controller.player.update((state) => ({
        ...state,
        presentationMode: "passive_clip",
        hasReplayableTracks: false,
        activeSegmentId: "confirmation",
        regions: [{ segmentId: "confirmation", sequence: -1, start: 0, end: 1, status: "ready", active: true, chapter: { kind: "passive", type: "confirmation" }, waveform: readyWaveform }],
      }));
      return controller;
    })(),
  },
};
