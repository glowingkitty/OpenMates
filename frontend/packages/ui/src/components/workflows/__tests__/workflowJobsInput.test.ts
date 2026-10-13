import { describe, expect, it } from 'vitest';
import { addJobRequest, jobCountriesSelection, jobCountryOverrides, jobRemoteSelection, jobRemoteValue, removeJobRequest, toggleJobCountry, updateJobRequestField } from '../workflowJobsInput';

describe('Jobs workflow search inputs', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
  it('saves DE, SE or both while preventing an empty selection', () => {
    const initial = { requests: [{ query: 'analyst', country: 'SE' }] };
    expect(jobCountriesSelection(initial)).toEqual(['SE']);
    const both = toggleJobCountry(initial, 'DE');
    expect(both.countries).toEqual(['DE', 'SE']);
    expect(both.requests).toEqual([{ query: 'analyst' }]);
    const de = toggleJobCountry(both, 'SE');
    expect(de.countries).toEqual(['DE']);
    expect(toggleJobCountry(de, 'DE')).toBe(de);
    expect(toggleJobCountry(de, 'SE').countries).toEqual(['DE', 'SE']);
    expect(jobCountriesSelection({ requests: [{ query: 'neutral' }] })).toEqual(['DE']);
    const mixedLegacy = { requests: [{ query: 'analyst', country: 'SE' }, { query: 'engineer', countries: ['DE'] }] };
    expect(jobCountriesSelection(mixedLegacy)).toEqual(['DE', 'SE']);
    expect(jobCountryOverrides(mixedLegacy)).toEqual([{ index: 0, countries: ['SE'] }, { index: 1, countries: ['DE'] }]);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
  it('keeps an unrestricted remote filter absent and preserves both explicit choices', () => {
    const initial = { query: 'software engineer', country: 'SE' };
    expect(jobRemoteSelection(undefined)).toBe('');
    expect(jobRemoteValue('')).toBeUndefined();
    const remote = updateJobRequestField(initial, 'remote', jobRemoteValue('true'));
    expect(remote.remote).toBe(true);
    const onsite = updateJobRequestField(remote, 'remote', jobRemoteValue('false'));
    expect(onsite.remote).toBe(false);
    expect(updateJobRequestField(onsite, 'remote', jobRemoteValue(''))).toEqual(initial);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring
  it('adds up to five independent requests and retains at least one on removal', () => {
    let requests = [{ query: 'engineer' }];
    for (let index = 0; index < 4; index += 1) {
      requests = addJobRequest(requests, () => ({ query: `role ${index}` }));
    }
    expect(requests.map(request => request.query)).toEqual(['engineer', 'role 0', 'role 1', 'role 2', 'role 3']);
    expect(addJobRequest(requests, () => ({ query: 'sixth' }))).toBe(requests);
    expect(removeJobRequest(requests, 2).map(request => request.query)).toEqual(['engineer', 'role 0', 'role 2', 'role 3']);
    expect(removeJobRequest([{ query: 'only' }], 0)).toEqual([{ query: 'only' }]);
  });
});
