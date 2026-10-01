import { describe, expect, it } from 'vitest';
import {
  expandCompositeSkillPaths, getSkillPath, prepareSkillInput, remainingSkillPaths, selectSkillSchema, setSkillPath,
  showAllSkillSchema, validateSkillInput, type SkillSchema,
} from '../appsSkillFormUtils';
import { staysMetadata, travelMetadata } from '../AppsSkillForm.preview';

// contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
describe('Apps skill request forms', () => {
  const schema: SkillSchema = {
    type: 'object', required: ['requests'], properties: {
      requests: { type: 'array', minItems: 1, items: { type: 'object', required: ['query', 'location'], properties: {
        query: { type: 'string', minLength: 1 }, location: { type: 'string' },
        duration: { type: 'integer', minimum: 1, maximum: 30 },
      } } },
      provider: { type: 'string', enum: ['first', 'second'] },
    },
  };

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
  it('projects primary fields without flattening the direct request', () => {
    const paths = ['requests[].query', 'requests[].location'];
    const primary = selectSkillSchema(schema, paths);
    expect(primary?.properties?.requests?.items?.properties).toEqual({
      query: { type: 'string', minLength: 1 }, location: { type: 'string' },
    });
    expect(remainingSkillPaths(schema, paths)).toEqual(['requests[].duration', 'provider']);
    const input = setSkillPath({ requests: [{ duration: 5 }], provider: 'first' }, 'requests[].query', 'jazz');
    expect(getSkillPath(input, 'requests[].query')).toBe('jazz');
    expect(input).toEqual({ requests: [{ duration: 5, query: 'jazz' }], provider: 'first' });
  });

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
  it('catches missing nested values and invalid settings before dispatch', () => {
    expect(validateSkillInput(schema, { requests: [{ query: 'jazz', duration: 50 }], provider: 'unknown' })).toEqual([
      { path: 'requests[0].location', code: 'required' },
      { path: 'requests[0].duration', code: 'maximum' },
      { path: 'provider', code: 'enum' },
    ]);
  });

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
  it('resolves local references and nullable fields for form controls', () => {
    const referenced: SkillSchema = {
      type: 'object', properties: {
        place: { $ref: '#/$defs/place' },
        note: { anyOf: [{ type: 'string' }, { type: 'null' }] },
      },
      $defs: { place: { type: 'string', title: 'City' } },
    };
    const projected = selectSkillSchema(referenced, ['place', 'note']);
    const shown = showAllSkillSchema(projected!);
    expect(shown.properties?.place).toMatchObject({ type: 'string', title: 'City' });
    expect(shown.properties?.note).toMatchObject({ type: 'string' });
    expect(validateSkillInput(referenced, { place: 'Berlin', note: null })).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
  it('projects Travel legs into two primary controls and leaves required date in settings', () => {
    const travel = travelMetadata.input_schema as SkillSchema;
    const primary = travelMetadata.primary_fields;
    const item = selectSkillSchema(travel, primary)?.properties?.requests?.items?.properties?.legs?.items;
    expect(Object.keys(item?.properties ?? {})).toEqual(['origin', 'destination']);
    expect(remainingSkillPaths(travel, primary)).toContain('requests[].legs[].date');
    expect(validateSkillInput(travel, { requests: [{ legs: [{ origin: 'Munich', destination: 'Berlin' }] }] }))
      .toContainEqual({ path: 'requests[0].legs[0].date', code: 'required' });
  });

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
  it('renders a declared stay date range as one slot and submits literal dates', () => {
    const stays = staysMetadata.input_schema as SkillSchema;
    const primary = expandCompositeSkillPaths(stays, staysMetadata.primary_fields);
    expect(primary).toEqual(['requests[].query', 'requests[].check_in_date', 'requests[].check_out_date']);
    expect(remainingSkillPaths(stays, primary)).not.toContain('requests[].check_out_date');
    const prepared = prepareSkillInput(stays, { requests: [{ query: 'Hotels in Paris', adults: 2,
      check_in_date: { $date: 'today', format: 'date' }, check_out_date: { $date: 'next_seven_days_end', format: 'date' },
    }] }, 'UTC', new Date('2026-09-30T12:00:00Z'));
    expect(prepared).toEqual({ requests: [{ query: 'Hotels in Paris', adults: 2,
      check_in_date: '2026-09-30', check_out_date: '2026-10-06',
    }] });
    expect(validateSkillInput(stays, prepared)).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
  it('drops a hidden compatibility day count only when a date range is selected', () => {
    const weather: SkillSchema = { type: 'object', 'x-ui': { control: 'date-range', start_field: 'start_date', end_field: 'end_date' },
      properties: { location: { type: 'string' }, start_date: { type: 'string', format: 'date' }, end_date: { type: 'string', format: 'date' },
        days: { type: 'integer', default: 7, 'x-ui': { hidden: true } },
      }, required: ['location'],
    };
    const noRange = prepareSkillInput(weather, { location: 'Berlin', days: 7 }, 'UTC', new Date('2026-09-30T12:00:00Z'));
    expect(noRange).toEqual({ location: 'Berlin', days: 7 });
    const withRange = prepareSkillInput(weather, { location: 'Berlin', days: 7,
      start_date: { $date: 'today', format: 'date' }, end_date: { $date: 'today', format: 'date' },
    }, 'UTC', new Date('2026-09-30T12:00:00Z'));
    expect(withRange).toEqual({ location: 'Berlin', start_date: '2026-09-30', end_date: '2026-09-30' });
  });
});
