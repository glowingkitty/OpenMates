/**
 * Interactive preview state for the Figma-defined assistant speech player.
 * Exercises chapter navigation, pending waveform hydration, pause, and close.
 * No network, audio provider, encrypted asset, or persisted chat data is used.
 * Access at: /dev/preview/AssistantSpeechPlayer
 */

import { writable } from "svelte/store";

const readyWaveform = [32, 58, 82, 44, 72, 96, 54, 76, 38, 68, 88, 48];

function createPreviewController() {
  const player = writable({
    responseId: "preview-response",
    chatId: "preview-chat",
    messageId: "preview-message",
    status: "playing",
    activeSegmentId: "segment-1",
    error: null,
    presentationMode: "replayable_track_queue",
    hasReplayableTracks: true,
    mateName: "Sophia",
    mateCategory: "calendar",
    regions: [
      { segmentId: "segment-0", sequence: 0, start: 0, end: 0.28, status: "ready", active: false, chapter: { kind: "heading", text: "Short answer" }, waveform: readyWaveform },
      { segmentId: "segment-1", sequence: 1, start: 0.28, end: 0.72, status: "ready", active: true, chapter: { kind: "heading", text: "Key considerations" }, waveform: readyWaveform },
      { segmentId: "segment-2", sequence: 2, start: 0.72, end: 1, status: "generating", active: false, chapter: { kind: "heading", text: "Optimization" }, waveform: [] },
    ],
  });

  function updateStatus(status: string) {
    player.update((state) => ({ ...state, status }));
  }

  return {
    player,
    pause: () => updateStatus("paused"),
    play: async () => updateStatus("playing"),
    previous: async () => player.update((state) => ({ ...state, activeSegmentId: "segment-0", status: "playing", regions: state.regions.map((region) => ({ ...region, active: region.segmentId === "segment-0" })) })),
    next: async () => {
      player.update((state) => ({ ...state, activeSegmentId: "segment-2", status: "waiting_for_segment", regions: state.regions.map((region) => ({ ...region, active: region.segmentId === "segment-2" })) }));
      window.setTimeout(() => {
        player.update((state) => ({ ...state, status: "playing", regions: state.regions.map((region) => region.segmentId === "segment-2" ? { ...region, status: "ready", waveform: readyWaveform } : region) }));
      }, 500);
    },
    selectSegment: async () => {},
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
