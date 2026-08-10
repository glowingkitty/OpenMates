/*
 * Design icon export helpers.
 *
 * Purpose: fetch sanitized Iconify SVGs from OpenMates and export them locally.
 * Architecture: clients call only OpenMates API routes, never Iconify directly.
 * Security: icon paths and color values are strictly validated before use.
 * Tests: frontend/packages/openmates-cli/tests/sdk.test.ts and cli.test.ts.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, extname } from "node:path";
import { Resvg } from "@resvg/resvg-js";

export type DesignIconExportFormat = "svg" | "png";

export interface DesignIconExportOptions {
  svgPath?: string;
  prefix?: string;
  name?: string;
  format?: DesignIconExportFormat;
  outputPath?: string;
  color?: string;
  palette?: boolean;
  allowPaletteRecolor?: boolean;
  size?: number;
  width?: number;
  height?: number;
}

export interface DesignIconExportRequest extends DesignIconExportOptions {
  fetchSvg: (path: string) => Promise<ArrayBuffer | Uint8Array | string>;
}

export interface DesignIconExportResult {
  format: DesignIconExportFormat;
  contentType: "image/svg+xml" | "image/png";
  data: Uint8Array;
  svg: string;
  svgPath: string;
  outputPath?: string;
}

const ICON_SEGMENT_PATTERN = /^[a-z0-9][a-z0-9._-]*$/i;
const ICON_PATH_PATTERN = /^\/v1\/apps\/design\/icons\/iconify\/([a-z0-9][a-z0-9._-]*)\/([a-z0-9][a-z0-9._-]*)\.svg$/i;
const HEX_COLOR_PATTERN = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const DEFAULT_PNG_SIZE = 256;
const MAX_PNG_SIZE = 4096;

export async function exportDesignIcon(request: DesignIconExportRequest): Promise<DesignIconExportResult> {
  const svgPath = resolveDesignIconSvgPath(request);
  const format = resolveDesignIconFormat(request.format, request.outputPath);
  const color = normalizeDesignIconColor(request.color);
  if (color && request.palette === true && request.allowPaletteRecolor !== true) {
    throw new Error("Palette icons cannot be recolored unless allowPaletteRecolor is true");
  }

  const fetched = await request.fetchSvg(svgPath);
  const svg = applyDesignIconColor(decodeFetchedSvg(fetched), color);
  const data = format === "svg" ? new TextEncoder().encode(svg) : renderDesignIconPng(svg, request);
  const result: DesignIconExportResult = {
    format,
    contentType: format === "svg" ? "image/svg+xml" : "image/png",
    data,
    svg,
    svgPath,
    outputPath: request.outputPath,
  };
  if (request.outputPath) {
    await writeExportFile(request.outputPath, data);
  }
  return result;
}

export function resolveDesignIconSvgPath(options: Pick<DesignIconExportOptions, "svgPath" | "prefix" | "name">): string {
  if (options.svgPath) {
    const trimmed = options.svgPath.trim();
    if (!ICON_PATH_PATTERN.test(trimmed)) {
      throw new Error("svgPath must be an OpenMates Design Iconify SVG path");
    }
    return trimmed;
  }
  const prefix = options.prefix?.trim();
  const name = options.name?.trim();
  if (!prefix || !name) {
    throw new Error("Provide either svgPath or both prefix and name");
  }
  if (!ICON_SEGMENT_PATTERN.test(prefix) || !ICON_SEGMENT_PATTERN.test(name)) {
    throw new Error("Icon prefix and name may contain only letters, numbers, dots, underscores, and dashes");
  }
  return `/v1/apps/design/icons/iconify/${encodeURIComponent(prefix)}/${encodeURIComponent(name)}.svg`;
}

export function normalizeDesignIconColor(color: string | undefined): string | undefined {
  if (color === undefined) return undefined;
  const trimmed = color.trim();
  if (!HEX_COLOR_PATTERN.test(trimmed)) {
    throw new Error("Icon color must be a hex color such as #111827");
  }
  return trimmed;
}

export function applyDesignIconColor(svg: string, color: string | undefined): string {
  if (!color) return svg;
  const withCurrentColor = svg.replace(/\bcurrentColor\b/g, color);
  return withCurrentColor.replace(/<svg\b([^>]*)>/i, (match, attrs: string) => {
    if (/\scolor\s*=/.test(attrs)) {
      return match.replace(/\scolor\s*=\s*(['"])[^'"]*\1/i, ` color="${color}"`);
    }
    return `<svg${attrs} color="${color}">`;
  });
}

function resolveDesignIconFormat(format: DesignIconExportFormat | undefined, outputPath: string | undefined): DesignIconExportFormat {
  if (format) return format;
  const extension = outputPath ? extname(outputPath).toLowerCase() : ".svg";
  return extension === ".png" ? "png" : "svg";
}

function decodeFetchedSvg(value: ArrayBuffer | Uint8Array | string): string {
  if (typeof value === "string") return value;
  return new TextDecoder().decode(value);
}

function renderDesignIconPng(svg: string, options: Pick<DesignIconExportOptions, "size" | "width" | "height">): Uint8Array {
  const width = normalizePngSize(options.width, "width");
  const height = normalizePngSize(options.height, "height");
  const size = normalizePngSize(options.size, "size") ?? DEFAULT_PNG_SIZE;
  const fitTo = width
    ? { mode: "width" as const, value: width }
    : height
      ? { mode: "height" as const, value: height }
      : { mode: "width" as const, value: size };
  return new Uint8Array(new Resvg(svg, { fitTo, logLevel: "off" }).render().asPng());
}

function normalizePngSize(value: number | undefined, label: string): number | undefined {
  if (value === undefined) return undefined;
  if (!Number.isInteger(value) || value <= 0 || value > MAX_PNG_SIZE) {
    throw new Error(`PNG ${label} must be an integer from 1 to ${MAX_PNG_SIZE}`);
  }
  return value;
}

async function writeExportFile(path: string, data: Uint8Array): Promise<void> {
  const directory = dirname(path);
  if (directory && directory !== ".") {
    await mkdir(directory, { recursive: true });
  }
  await writeFile(path, data);
}
