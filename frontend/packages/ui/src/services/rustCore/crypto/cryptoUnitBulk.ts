import type { WebCryptoBulkOp, WebCryptoBulkResult } from './webCryptoClient';
import { WEB_CRYPTO_BULK_OPS } from './webCryptoClient';

type Fn = (...args: unknown[]) => Promise<unknown>;
type Binding = Record<string, unknown>;

/** Rust list exports of the crypto unit, one per bulk op. */
const BULK_EXPORT_BY_OP: Record<WebCryptoBulkOp, string> = {
  decryptChatContent: 'webCryptoBulkDecryptChat',
  encryptChatContent: 'webCryptoBulkEncryptChat',
  masterDecrypt: 'webCryptoBulkMasterDecrypt',
};
export const BULK_EXPORTS = Object.values(BULK_EXPORT_BY_OP);

/**
 * Bulk path of the crypto unit: one Rust call per list. Rust owns the formats
 * and the attempt policy and issues every AES-GCM primitive of the list at once
 * through its web AEAD adapter (this Worker's WebCrypto); this adapter only
 * checks the request shape and wraps the result.
 */
export function createBulkRunner(binding: Binding) {
  const fn = (name: string) => binding[name] as Fn;
  return async function runBulk(args: unknown[]): Promise<WebCryptoBulkResult> {
    const [op, key, items] = args as [WebCryptoBulkOp, unknown, unknown];
    if (!WEB_CRYPTO_BULK_OPS.has(op) || !Array.isArray(items) || !items.every((item) => typeof item === 'string')) {
      throw new Error('rust_web_crypto_bad_request');
    }
    if (op === 'masterDecrypt') {
      if (!(key instanceof CryptoKey)) throw new Error('crypto');
      return (await fn(BULK_EXPORT_BY_OP.masterDecrypt)(key, items)) as WebCryptoBulkResult;
    }
    if (!(key instanceof Uint8Array)) throw new Error('crypto');
    return { values: (await fn(BULK_EXPORT_BY_OP[op])(key, items)) as unknown[], errors: [] };
  };
}
