import type { DesignDocument, DesignFont, DesignLayer, DesignPage } from './designDocument';
import cliff from './assets/cliff.webp';
import arch from './assets/arch.webp';
import dunes from './assets/dunes.webp';

function box(id: string, name: string, x: number, y: number, width: number, height: number, rotation = 0) {
  return { id, name, x, y, width, height, rotation };
}

function rect(id: string, name: string, x: number, y: number, w: number, h: number, color: string, radius = 0): DesignLayer {
  return { ...box(id, name, x, y, w, h), kind: 'shape', shape: 'rectangle', color, radius };
}

function circle(id: string, name: string, x: number, y: number, diameter: number, color: string): DesignLayer {
  return { ...box(id, name, x, y, diameter, diameter), kind: 'shape', shape: 'ellipse', color };
}

function words(id: string, name: string, value: string, x: number, y: number, w: number, h: number, fontSize: number,
  color: string, font: DesignFont = 'Sans', weight = 700): DesignLayer {
  return { ...box(id, name, x, y, w, h), kind: 'text', text: value, font, fontSize, weight, color };
}

function photo(id: string, name: string, src: string, x: number, y: number, w: number, h: number, rotation = 0): DesignLayer {
  return { ...box(id, name, x, y, w, h, rotation), kind: 'image', src };
}

function vector(id: string, name: string, path: string, x: number, y: number, w: number, h: number, color: string): DesignLayer {
  return { ...box(id, name, x, y, w, h), kind: 'path', path, viewWidth: 100, viewHeight: 100, color };
}

function page(id: string, name: string, width: number, height: number, background: string, layers: DesignLayer[]): DesignPage {
  return { id, name, width, height, background, layers };
}

const navy = '#17294b';
const cream = '#fff0ce';
const coral = '#ff775c';
const blue = '#385cb5';
const wave = 'M0 67 C17 67 20 18 40 18 S64 75 80 75 Q91 75 100 35 L100 100 L0 100 Z';
const star = 'M50 0 Q57 43 100 50 Q57 57 50 100 Q43 57 0 50 Q43 43 50 0 Z';

export const flyer: DesignDocument = {
  title: 'Afterlight · event flyer',
  pages: [page('flyer', 'Flyer', 640, 800, cream, [
    rect('field', 'Indigo field', 24, 24, 592, 752, navy),
    circle('sun', 'Setting sun', 356, 310, 180, coral),
    vector('wave', 'Blue ridge', wave, 24, 333, 592, 267, blue),
    vector('star', 'Evening star', star, 73, 384, 63, 63, cream),
    words('series', 'Series label', 'SOUND IN THE GARDEN  /  VOL. 04', 64, 64, 518, 33, 20, cream, 'Mono'),
    words('headline', 'Afterlight headline', 'Afterlight', 59, 132, 533, 123, 106, cream, 'Serif', 400),
    words('tagline', 'Tagline', 'An open-air listening night', 68, 257, 497, 44, 29, cream, 'Sans', 400),
    rect('rule', 'Footer rule', 64, 638, 510, 2, cream),
    words('date', 'Date & time', 'FRI 18 JUL  /  19:30', 64, 655, 500, 35, 25, cream, 'Mono'),
    words('venue', 'Venue', 'THE GLASS GARDEN   ·   BRIGHTON', 64, 711, 510, 28, 17, cream, 'Mono', 400)
  ])]
};

export const collage: DesignDocument = {
  title: 'Atlantic field notes · collage',
  pages: [page('collage', 'Collage', 800, 630, '#eee6d5', [
    rect('border', 'Ruled border', 26, 25, 748, 2, '#4e5747'),
    words('edition', 'Edition', 'FIELD NOTES  /  01', 31, 46, 360, 30, 20, '#4e5747', 'Mono'),
    words('heading', 'Collage title', 'Atlantic light', 29, 83, 737, 110, 90, '#253c37', 'Serif', 400),
    photo('cliff', 'Coastal cliff', cliff, 45, 215, 230, 339, -6),
    photo('arch', 'Stucco arch', arch, 287, 207, 226, 342, 3),
    photo('dunes', 'Beach grasses', dunes, 529, 218, 227, 334, -3),
    words('footnote', 'Location', 'ESTREMADURA, PORTUGAL  ·  38° 42′ N', 34, 581, 728, 30, 20, '#4e5747', 'Mono', 400)
  ])]
};

export const social: DesignDocument = {
  title: 'Good things grow slowly · social post',
  pages: [page('post', 'Square post', 720, 720, '#dee7b9', [
    circle('halo', 'Lavender halo', 396, 56, 243, '#b9b0e1'),
    vector('leaf', 'Fern silhouette', 'M47 100 L54 41 Q21 46 14 4 Q50 8 58 35 Q68 12 94 10 Q83 45 61 48 L55 100 Z', 454, 79, 198, 224, '#354b38'),
    words('name', 'Series name', 'THE SUNDAY GROWERS CLUB', 46, 50, 440, 31, 19, '#354b38', 'Mono'),
    words('title', 'Main message', 'Good things\ngrow slowly.', 44, 271, 632, 217, 87, '#26372b', 'Serif', 400),
    rect('rule', 'Footer rule', 46, 616, 628, 2, '#354b38'),
    words('footer', 'Post caption', 'A SMALL REMINDER FOR SPRING', 46, 637, 625, 30, 19, '#354b38', 'Mono')
  ])]
};

const ink = '#252d35';
const mint = '#c6e5cf';
function appScreen(id: string, name: string, title: string, subtitle: string, rows: string[]) {
  return page(id, name, 390, 700, '#f7f6f0', [
    words('status', 'Status bar', '9:41', 27, 23, 70, 30, 17, ink),
    words('brand', 'App name', 'TRAIL  /  CLUB', 28, 72, 334, 25, 15, ink, 'Mono'),
    words('title', 'Screen title', title, 27, 121, 345, 68, 42, ink, 'Serif', 400),
    words('subtitle', 'Screen subtitle', subtitle, 28, 183, 333, 31, 16, ink, 'Sans', 400),
    rect('card', 'Feature card', 26, 229, 338, 171, mint, 18),
    vector('terrain', 'Contour', wave, 45, 249, 300, 117, '#397360'),
    ...rows.flatMap((row, index) => [
      rect(`item-${index}`, `Row ${index + 1}`, 26, 423 + index * 59, 338, 48, '#e9ebdf', 12),
      words(`label-${index}`, row, row, 44, 435 + index * 59, 302, 27, 17, ink)
    ]),
    words('navigation', 'Tab labels', 'Explore       Saved       Profile', 35, 649, 332, 35, 17, ink)
  ]);
}

export const mockup: DesignDocument = {
  title: 'Trail Club · app mockup',
  pages: [
    appScreen('explore', 'Explore', 'Find a trail', 'A little further from the city.', ['Pine Ridge', 'Coastal Loop', 'River Walk']),
    appScreen('saved', 'Saved', 'Saved trails', 'Ready when you are.', ['North Bluff', 'Meadow Path']),
    appScreen('profile', 'Profile', 'Your profile', 'Keep track of time outdoors.', ['Recent walks', 'Club membership'])
  ]
};

export function stressDesign(count: number): DesignDocument {
  const palette = ['#4763a3', '#ff886c', '#bddbd3', '#f6d994', '#9590bf', '#29416d'];
  const layers = Array.from({ length: count - 1 }, (_, index): DesignLayer => {
    const id = `tile-${index}`;
    const name = `Tile ${index + 1}`;
    const x = 18 + (index % 25) * 31;
    const y = 83 + Math.floor(index / 25) * (440 / Math.ceil(count / 25));
    const color = palette[(index * 7 + Math.floor(index / 25)) % palette.length];
    if (index % 11 === 0) return words(id, name, String(index), x, y, 28, 20, 11, color, 'Mono');
    if (index % 7 === 0) return vector(id, name, star, x, y, 26, 23, color);
    if (index % 3 === 0) return circle(id, name, x, y, 20, color);
    return rect(id, name, x, y, 27, 14, color, 3);
  });
  return {
    title: `Pattern study · ${count} layers`,
    pages: [page('stress', 'Pattern study', 812, 570, '#f7f5ee', [
      ...layers, words('headline', 'Study title', 'Pattern study', 18, 19, 432, 57, 44, navy, 'Serif', 400)
    ])]
  };
}
