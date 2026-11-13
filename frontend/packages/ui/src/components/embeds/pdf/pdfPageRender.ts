// frontend/packages/ui/src/components/embeds/pdf/pdfPageRender.ts
//
// Asks the backend to prepare one page image of an uploaded PDF (PDF processing v2: only page 1
// is rendered during processing, every other page is rendered, safety-checked and encrypted the
// first time someone views it). The response contains only the S3 key and a status; the page
// itself is downloaded and decrypted client-side with the key the embed already holds.

import { getApiUrl } from '../../../config/api';

export type PdfPageRenderStatus = 'ok' | 'withheld' | 'rejected' | 'unavailable';

export interface PdfPageRenderResult {
  status: PdfPageRenderStatus;
  s3Key?: string;
}

export async function requestPdfPageRender(
  embedId: string,
  pageNumber: number,
): Promise<PdfPageRenderResult> {
  const endpoint = `${getApiUrl()}/v1/embeds/${encodeURIComponent(embedId)}/pdf-pages/${pageNumber}/render`;
  const response = await fetch(endpoint, { method: 'POST', credentials: 'include' });
  if (response.status === 404 || response.status === 409) {
    return { status: 'unavailable' };
  }
  if (!response.ok) {
    throw new Error(`PDF page render failed: ${response.status}`);
  }
  const data = (await response.json()) as { status: PdfPageRenderStatus; s3_key?: string | null };
  return { status: data.status, s3Key: data.s3_key ?? undefined };
}
