/**
 * Scopes for large-preview carousels.
 *
 * The slides of one large-preview carousel are separate components that share
 * their active index, shell height and card bounds through keyed stores. The
 * run key alone (the run's first embed ref) is not unique: the same embed can
 * be rendered by several message views at once, each at its own width. Every
 * rendering surface therefore owns a scope, and the store key combines that
 * scope with the run key, so one view never sizes another view's carousel
 * (issue X83Z4: a narrow copy pinned a wide card's wrapper to 204px).
 */

let nextScope = 0;
const ownerScopes = new WeakMap<object, string>();

/** A fresh scope for a surface that renders exactly one carousel. */
export function createEmbedCarouselScope(): string {
  nextScope += 1;
  return `carousel-scope-${nextScope}`;
}

/** The stable scope of a surface (e.g. one message editor) that renders all slides of its runs. */
export function embedCarouselScopeFor(owner: object): string {
  let scope = ownerScopes.get(owner);
  if (!scope) {
    scope = createEmbedCarouselScope();
    ownerScopes.set(owner, scope);
  }
  return scope;
}
