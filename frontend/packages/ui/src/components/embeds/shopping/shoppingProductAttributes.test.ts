import { describe, expect, it } from 'vitest';
import { shoppingProductAttributes } from './shoppingProductAttributes';

describe('supplied product specifications and legacy attributes', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful
  it('renders admitted named specifications alongside existing attributes', () => {
    expect(shoppingProductAttributes({Material:'Steel'},[{name:'Capacity',value:'1.5 L'}]))
      .toEqual({Capacity:'1.5 L',Material:'Steel'});
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts
  it('preserves explicit false/zero and existing attribute precedence', () => {
    expect(shoppingProductAttributes({Capacity:'2 L',is_vegan:false},[{name:'Capacity',value:'1.5 L'},{name:'Count',value:0},{name:'Reusable',value:false}]))
      .toEqual({Capacity:'2 L',Count:0,Reusable:false,is_vegan:false});
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts
  it('does not fabricate attributes from missing or malformed specifications', () => {
    expect(shoppingProductAttributes(undefined,[null,{name:'',value:'x'},{name:'Unknown'},{name:'Object',value:{}}])).toBeUndefined();
  });
});
