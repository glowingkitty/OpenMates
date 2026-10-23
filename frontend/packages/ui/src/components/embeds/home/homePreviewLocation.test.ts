import { afterEach, describe, expect, it, vi } from 'vitest';
import { homeCityGeometry, homePreviewCity, resolveHomePreviewCity } from './homePreviewLocation';
vi.mock('../../../config/api', () => ({getApiUrl: () => 'https://api.example.test'}));
const city = {name: 'Hamburg', addresstype: 'city', boundingbox: ['53.39', '53.74', '9.73', '10.33'], address: {city: 'Hamburg'}};
afterEach(() => vi.unstubAllGlobals());
describe('Home preview municipality geometry', () => {
  // contract-test: direct surface=gui.web assertions=home-search.location.precision,home-search.web.map-and-filter
  it('extracts only municipality text and never sends a street as a fallback query', () => {
    expect(homePreviewCity(undefined, 'Bergmannstr. 12, 10961 Berlin')).toBe('Berlin');
    expect(homePreviewCity('Hamburg', 'Private street 23, Berlin')).toBe('Hamburg');
    expect(homePreviewCity(undefined, 'Undisclosed street 12')).toBeUndefined();
    expect(homePreviewCity(undefined, 'Schönhauser Allee')).toBeUndefined();
    expect(homePreviewCity(undefined, '')).toBeUndefined();
  });
  // contract-test: direct surface=gui.web assertions=home-search.location.precision,home-search.web.map-and-filter
  it('derives an approximate circle only from matching municipality bounds', () => {
    const geometry = homeCityGeometry([city], 'Hamburg');
    expect(geometry).toMatchObject({areaBasis: 'city'});
    expect(geometry!.lat).toBeCloseTo(53.565);
    expect(geometry!.lon).toBeCloseTo(10.03);
    expect(geometry!.radiusM).toBeGreaterThan(27000);
    expect(geometry!.radiusM).toBeLessThan(29000);
    expect(homeCityGeometry([{...city, addresstype: 'house'}], 'Hamburg')).toBeUndefined();
    expect(homeCityGeometry([city], 'Berlin')).toBeUndefined();
    expect(homeCityGeometry([{...city, boundingbox: undefined, lat: '53.5', lon: '10'}], 'Hamburg')).toBeUndefined();
    expect(homeCityGeometry([{...city, boundingbox: ['-91', '91', '-181', '181']}], 'Hamburg')).toBeUndefined();
    expect(homeCityGeometry([city, {...city, boundingbox: ['40', '41', '20', '21']}], 'Hamburg')).toBeUndefined();
  });
  // contract-test: supporting surface=gui.web assertions=home-search.location.precision,home-search.web.map-and-filter
  it('deduplicates city requests through the existing first-party proxy', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) => ({ok: true, json: async () => [city]}));
    vi.stubGlobal('fetch', fetcher);
    const [first, second] = await Promise.all([resolveHomePreviewCity('Hamburg'), resolveHomePreviewCity('Hamburg')]);
    expect(first).toEqual(second);
    expect(first?.areaBasis).toBe('city');
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe('https://api.example.test/v1/geocode/search?q=Hamburg&limit=3&addressdetails=1');
  });
  // contract-test: supporting surface=gui.web assertions=home-search.location.precision
  it('keeps failed lookups unavailable and retriable rather than inventing coordinates', async () => {
    const fetcher = vi.fn(async () => ({ok: false}));
    vi.stubGlobal('fetch', fetcher);
    expect(await resolveHomePreviewCity('Unavailable municipality')).toBeUndefined();
    expect(await resolveHomePreviewCity('Unavailable municipality')).toBeUndefined();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
