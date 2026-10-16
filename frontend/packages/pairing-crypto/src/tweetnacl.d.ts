declare module 'tweetnacl' {
  interface Box {
    (message: Uint8Array, nonce: Uint8Array, publicKey: Uint8Array, secretKey: Uint8Array): Uint8Array;
    open(message: Uint8Array, nonce: Uint8Array, publicKey: Uint8Array, secretKey: Uint8Array): Uint8Array | null;
    keyPair(): { publicKey: Uint8Array; secretKey: Uint8Array };
  }
  interface ScalarMult {
    (secretKey: Uint8Array, publicKey: Uint8Array): Uint8Array;
    base(secretKey: Uint8Array): Uint8Array;
  }
  const nacl: { randomBytes(length: number): Uint8Array; box: Box; scalarMult: ScalarMult };
  export default nacl;
}
