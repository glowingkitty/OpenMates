// frontend/packages/ui/src/stores/__tests__/appSkillsStore.test.ts
//
// Regression coverage for Settings > Apps user-specific skill filtering.
// App discovery retains active apps with memories even when the authenticated
// skill response does not list them.

import { get } from "svelte/store";
import type { AppMetadata } from "../../types/apps";

import { afterEach, describe, expect, it } from "vitest";

import {
  appSkillsStore,
  selectDiscoverableApps,
  discoverableApps,
  featureAvailabilityStore,
  resetFeatureAvailability,
  resetUserAvailableSkills,
  userAvailableSkillsStore,
} from "../appSkillsStore";

describe("appSkillsStore", () => {
  afterEach(() => {
    resetFeatureAvailability();
    resetUserAvailableSkills();
  });

  // contract-test: direct surface=gui.web assertions=settings-ui.navigation.contextual-availability,workspace-shell.nav.released-surfaces-visible
  it("keeps unreleased workspace apps hidden until feature availability confirms they are enabled", () => {
    const apps = appSkillsStore.getState().apps;

    expect(apps.plans).toBeUndefined();
    expect(apps.projects).toBeUndefined();
    expect(apps.tasks).toBeUndefined();
    expect(apps.workflows).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.navigation.contextual-availability
  it("retains Diagram Design metadata without user-available skills", () => {
    userAvailableSkillsStore.set({
      initialized: true,
      loading: false,
      appsById: null,
      skillsByApp: {
        code: ["code"],
      },
    });

    const apps = appSkillsStore.getState().apps;

    expect(apps.diagrams).toMatchObject({
      id: "diagrams",
      name_translation_key: "apps.diagrams",
      skills: [],
    });
    expect(apps.diagrams.memories.length).toBeGreaterThan(0);
  });

  // contract-test: direct surface=gui.web assertions=settings-ui.navigation.contextual-availability
  it("omits apps disabled by effective feature availability", () => {
    featureAvailabilityStore.set({
      initialized: true,
      loading: false,
      disabledById: { "app:videos": true },
    });

    const apps = appSkillsStore.getState().apps;

    expect(apps.videos).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.navigation.contextual-availability
  it("filters disabled skills and recomputes providers", () => {
    featureAvailabilityStore.set({
      initialized: true,
      loading: false,
      disabledById: { "skill:web:search": true },
    });

    const web = appSkillsStore.getState().apps.web;

    expect(web.skills.some((skill) => skill.id === "search")).toBe(false);
    expect(web.providers ?? []).not.toContain("Brave");
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.navigation.contextual-availability
  it("filters disabled settings and memory fields", () => {
    featureAvailabilityStore.set({
      initialized: true,
      loading: false,
      disabledById: { "memory:ai:communication_style": true },
    });

    const ai = appSkillsStore.getState().apps.ai;

    expect(ai.settings_and_memories.some((memory) => memory.id === "communication_style")).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.navigation.contextual-availability
  it("overlays runtime provider and model availability from app metadata", () => {
    userAvailableSkillsStore.set({
      initialized: true,
      loading: false,
      skillsByApp: {
        ai: ["ask"],
      },
      appsById: {
        ai: {
          id: "ai",
          skills: [
            {
              id: "ask",
              name_translation_key: "app_translations.ai.skills.ask.name",
              description_translation_key: "app_translations.ai.skills.ask.description",
              providers: [{ name: "OpenAI", display_name: null, no_api_key: false }],
              models: [{ id: "gpt-4o-mini", provider_id: "openai" }],
            } as any,
          ],
          focus_modes: [],
          settings_and_memories: [],
          providers: [{ id: "openai", name: "OpenAI" }] as any,
        },
      },
    });

    const ai = appSkillsStore.getState().apps.ai;
    const ask = ai.skills.find((skill) => skill.id === "ask") as any;

    expect(ai.providers).toEqual(["OpenAI"]);
    expect(ask.models).toEqual([{ id: "gpt-4o-mini", provider_id: "openai" }]);
  });
});

const fixtureApp = (id: string, skills: string[] = [], focuses: string[] = []): AppMetadata => ({
  id, skills: skills.map(id => ({ id, name_translation_key: id, description_translation_key: id })),
  focus_modes: focuses.map(id => ({ id, name_translation_key: id, description_translation_key: id })),
  settings_and_memories: [{ id: 'saved', name_translation_key: 'saved' }] as AppMetadata['settings_and_memories'],
});

describe('discoverable Apps projection', () => {
  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog,settings-ui.navigation.contextual-availability
  it('requires usable capabilities while preserving raw memory metadata', () => {
    const apps = { memory: fixtureApp('memory'), skill: fixtureApp('skill', ['run']), focus: fixtureApp('focus', [], ['research']) };
    expect(Object.keys(selectDiscoverableApps(apps))).toEqual(['skill', 'focus']);
    expect(apps.memory.settings_and_memories).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog,settings-ui.navigation.contextual-availability
  it('retains explicitly enabled direct creation apps but excludes result renderers', () => {
    const ids = ['docs', 'mindmaps', 'diagrams', 'electronics', 'models3d', 'home'];
    const apps = Object.fromEntries(ids.map(id => [id, fixtureApp(id)]));
    expect(Object.keys(selectDiscoverableApps(apps))).toEqual(['docs', 'mindmaps', 'diagrams', 'electronics']);
    expect(selectDiscoverableApps(apps, {})).toEqual({});
    expect(Object.keys(selectDiscoverableApps(apps, { docs: fixtureApp('docs') }))).toEqual(['docs']);
  });

  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog,settings-ui.navigation.contextual-availability
  it('always omits internal workspace apps even when enabled with skills', () => {
    const ids = ['openmates', 'plans', 'projects', 'tasks', 'workflows'];
    const apps = Object.fromEntries(ids.map(id => [id, fixtureApp(id, ['run'])]));
    expect(selectDiscoverableApps(apps)).toEqual({});
    expect(selectDiscoverableApps({ hidden: { ...fixtureApp('hidden', ['run']), internal: true } })).toEqual({});
  });

  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog,settings-ui.navigation.contextual-availability
  it('honors authoritative runtime removal of apps, skills and focuses', () => {
    const apps = { skill: fixtureApp('skill', ['run']), focus: fixtureApp('focus', [], ['research']), missing: fixtureApp('missing', ['run']) };
    expect(selectDiscoverableApps(apps, { skill: fixtureApp('skill'), focus: fixtureApp('focus') })).toEqual({});
    expect(Object.keys(selectDiscoverableApps(apps, { focus: fixtureApp('focus', [], ['research']) }))).toEqual(['focus']);
    expect(Object.keys(selectDiscoverableApps(apps))).toEqual(['skill', 'focus', 'missing']);
  });

  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog,settings-ui.navigation.contextual-availability
  it('reacts to feature and successful runtime availability updates', () => {
    resetFeatureAvailability(); resetUserAvailableSkills();
    expect(get(discoverableApps).web).toBeDefined();
    userAvailableSkillsStore.set({ initialized: true, loading: false, skillsByApp: {}, appsById: {} });
    expect(get(discoverableApps)).toEqual({});
    resetUserAvailableSkills();
    featureAvailabilityStore.set({ initialized: true, loading: false, disabledById: { 'app:web': true } });
    expect(get(discoverableApps).web).toBeUndefined();
    resetFeatureAvailability(); resetUserAvailableSkills();
  });
});
