// figma-visual-proof: not-required. Original sample documents.
import { collage, flyer, mockup, social, stressDesign } from './designExamples';
import type { DesignDocument } from './designDocument';

export const layout = 'fill';

function fixture(document: DesignDocument, initialMode: 'view' | 'edit' = 'view') {
  return {
    document,
    initialMode,
    onClose: () => window.location.assign('/dev/preview')
  };
}

let currentStress: { count: number; props: ReturnType<typeof fixture> } | null = null;

function stressFixture(count: number) {
  if (currentStress?.count !== count) currentStress = { count, props: fixture(stressDesign(count), 'edit') };
  return currentStress.props;
}

export default fixture(flyer);

export const variants = {
  'flyer-edit': fixture(flyer, 'edit'),
  collage: fixture(collage),
  'social-post': fixture(social),
  'app-mockup': fixture(mockup),
  // Build only the selected stress fixture so cold-load and heap measurements scale with its layer count.
  get 'stress-50'() { return stressFixture(50); },
  get 'stress-100'() { return stressFixture(100); },
  get 'stress-250'() { return stressFixture(250); },
  get 'stress-500'() { return stressFixture(500); },
  get 'stress-1000'() { return stressFixture(1000); }
};
