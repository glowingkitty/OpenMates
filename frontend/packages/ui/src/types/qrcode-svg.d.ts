// frontend/packages/ui/src/types/qrcode-svg.d.ts
//
// Type declarations for qrcode-svg, which ships without TypeScript types.
// The library is used only to generate local SVG strings for QR codes in UI
// surfaces such as sharing, referrals, 2FA, and device pairing.
// Keep this declaration narrow to the constructor/options used by the app.

declare module 'qrcode-svg' {
  interface QRCodeSvgOptions {
    content: string;
    padding?: number;
    width?: number;
    height?: number;
    color?: string;
    background?: string;
    ecl?: 'L' | 'M' | 'Q' | 'H';
  }

  export default class QRCodeSVG {
    constructor(options: QRCodeSvgOptions);
    svg(): string;
  }
}
