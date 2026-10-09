/** The reviewed, same-origin PDF shipped with the public example chat. */
const EXAMPLE_PDF_PATH = '/store-examples/community-garden-budget.pdf';
const EXAMPLE_PAGE_IMAGE_PATH = '/store-examples/community-garden-budget-page-1.png';

export function publicExamplePdfUrl(value: unknown, hasPrivateCredentials = false): string | undefined {
  return !hasPrivateCredentials && value === EXAMPLE_PDF_PATH ? EXAMPLE_PDF_PATH : undefined;
}

/** Deterministic first-page render generated from the reviewed PDF bytes. */
export function publicExamplePdfPageImageUrl(value: unknown, hasPrivateCredentials = false): string | undefined {
  return publicExamplePdfUrl(value, hasPrivateCredentials) ? EXAMPLE_PAGE_IMAGE_PATH : undefined;
}
