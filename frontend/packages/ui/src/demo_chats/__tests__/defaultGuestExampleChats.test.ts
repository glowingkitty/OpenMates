import { describe, expect, it } from 'vitest';
import landingExamples from '../../generated/landingExampleChats.generated.json';
import { selectDefaultGuestExampleChats } from '../defaultGuestExampleChats';

const selectedIds = landingExamples.map(example => example.chatId);

describe('default guest continuation examples', () => {
  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment,landing-onboarding.guest-examples
  it('uses exactly the landing metadata selection and order, independently of catalog order', () => {
    const catalog = ['example-unselected', ...selectedIds.slice().reverse()].map(chat_id => ({ chat_id }));
    expect(selectDefaultGuestExampleChats(catalog, item => item.chat_id).map(item => item.chat_id)).toEqual(selectedIds);
    expect(selectedIds.length).toBeGreaterThan(10);
  });

  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment,landing-onboarding.guest-examples
  it('resolves current catalog objects afresh after a reload rather than retaining stale defaults', () => {
    const catalog = selectedIds.map(chat_id => ({ chat_id, title: 'old' }));
    selectDefaultGuestExampleChats(catalog, item => item.chat_id);
    const refreshedCatalog = catalog.map(item => ({ ...item, title: 'current' }));
    const refreshed = selectDefaultGuestExampleChats(refreshedCatalog, item => item.chat_id);
    expect(refreshed.map(item => item.chat_id)).toEqual(selectedIds);
    expect(refreshed.every(item => item.title === 'current')).toBe(true);
  });
});
