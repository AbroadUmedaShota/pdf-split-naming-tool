const requiredMetadata = ["box_no", "binder_no", "seq"] as const;
const invalidFilenameChars = /[<>:"/\\|?*]/g;

// 箱No・バインダーNoのゼロ埋め桁数（固定）。seqの桁数は seqDigits で可変。
const fixedTokenPads: ReadonlyArray<readonly [string, number]> = [
  ["box_no", 2],
  ["binder_no", 2]
];

export const DEFAULT_SEQ_DIGITS = 3;
export const MIN_SEQ_DIGITS = 1;
export const MAX_SEQ_DIGITS = 9;

export function coerceSeqDigits(value: unknown, fallback = DEFAULT_SEQ_DIGITS): number {
  const digits = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(digits)) {
    return fallback;
  }
  const rounded = Math.trunc(digits);
  if (rounded < MIN_SEQ_DIGITS) {
    return MIN_SEQ_DIGITS;
  }
  return Math.min(rounded, MAX_SEQ_DIGITS);
}

export type AffixPosition = "prefix" | "suffix";

export const AFFIX_POSITIONS: readonly AffixPosition[] = ["prefix", "suffix"];
export const MAX_AFFIX_COUNT = 2;

export type AffixDef = {
  key: string;
  label: string;
  position: AffixPosition;
};

export function padMetadata(value: string, length: number): string {
  return value.length >= length ? value : value.padStart(length, "0");
}

export function sanitizeFilename(filename: string): string {
  const sanitized = filename.replace(invalidFilenameChars, "_").trim().replace(/[. ]+$/g, "").replace(/\s+/g, " ");
  return sanitized || "output.pdf";
}

export function missingMetadata(metadata: Record<string, string>): string[] {
  return requiredMetadata.filter((key) => !String(metadata[key] ?? "").trim());
}

function affixTokens(
  metadata: Record<string, string>,
  affixDefs: ReadonlyArray<AffixDef>,
  position: AffixPosition
): string[] {
  return affixDefs
    .filter((definition) => definition.position === position && Boolean(definition.key))
    .map((definition) => String(metadata[definition.key] ?? "").trim())
    .filter((value) => value.length > 0);
}

export function previewFilename(
  metadata: Record<string, string>,
  affixDefs: ReadonlyArray<AffixDef> = [],
  seqDigits: number = DEFAULT_SEQ_DIGITS
): string {
  if (missingMetadata(metadata).length) {
    return "未入力";
  }
  const digits = coerceSeqDigits(seqDigits);
  const fixedTokens = fixedTokenPads.map(([key, width]) => padMetadata(String(metadata[key] ?? ""), width));
  fixedTokens.push(padMetadata(String(metadata.seq ?? ""), digits));
  const prefixes = affixTokens(metadata, affixDefs, "prefix");
  const suffixes = affixTokens(metadata, affixDefs, "suffix");
  const tokens = [...prefixes, ...fixedTokens, ...suffixes];
  return sanitizeFilename(`${tokens.join("_")}.pdf`);
}
