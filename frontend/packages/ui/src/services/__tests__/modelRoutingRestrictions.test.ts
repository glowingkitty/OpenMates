import { describe, expect, it } from 'vitest';
import { modelRoutingRestrictionsForTurn } from '../modelRoutingRestrictions';

describe('per-turn model routing restrictions', () => {
  // contract-test: supporting surface=gui.web assertions=ai-model-routing.defaults.google-tier-profiles
  it('copies only routing restrictions without modifying encrypted account state', () => {
    const profile = {
      disabled_ai_models: ['mercury-3'],
      disabled_ai_servers: { 'gemini-3.8-flash': ['google_ai_studio'] },
      default_ai_model_simple: 'anthropic/claude-sonnet-5-5',
      private_memory: 'must stay local',
    };
    const payload = modelRoutingRestrictionsForTurn(profile);
    expect(payload).toEqual({
      disabled_ai_models: ['mercury-3'],
      disabled_ai_servers: { 'gemini-3.8-flash': ['google_ai_studio'] },
      server_region_preference: 'eu',
    });
    payload.disabled_ai_models.push('another');
    payload.disabled_ai_servers['gemini-3.8-flash'].push('google');
    expect(profile.disabled_ai_models).toEqual(['mercury-3']);
    expect(profile.disabled_ai_servers['gemini-3.8-flash']).toEqual(['google_ai_studio']);
  });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.defaults.google-tier-profiles
  it('represents an unrestricted turn explicitly', () => {
    expect(modelRoutingRestrictionsForTurn({})).toEqual({ disabled_ai_models: [], disabled_ai_servers: {}, server_region_preference: 'eu' });
  });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.defaults.google-tier-profiles
  it('sends the Fastest, global region preference and defaults anything else to eu', () => {
    expect(modelRoutingRestrictionsForTurn({ server_region_preference: 'global' }).server_region_preference).toBe('global');
    expect(modelRoutingRestrictionsForTurn({ server_region_preference: 'eu' }).server_region_preference).toBe('eu');
  });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.defaults.google-tier-profiles
  it('fails closed instead of truncating a restriction or exposing invalid values', () => {
    expect(() => modelRoutingRestrictionsForTurn({ disabled_ai_models: ['private value'] })).toThrow('Invalid model routing restrictions');
    expect(() => modelRoutingRestrictionsForTurn({ disabled_ai_models: Array(257).fill('mercury-3') })).toThrow();
    expect(() => modelRoutingRestrictionsForTurn({ disabled_ai_servers: { 'mercury-3': Array(17).fill('inception') } })).toThrow();
  });
});
