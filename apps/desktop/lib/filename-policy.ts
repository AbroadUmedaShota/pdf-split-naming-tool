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

// Windows の予約デバイス名（大文字小文字・拡張子を問わず stem で照合する）。
// Python 側 domain.py の WINDOWS_RESERVED_STEMS と必ず同一に保つこと。
const windowsReservedStems = new Set([
  "CON",
  "PRN",
  "AUX",
  "NUL",
  ...Array.from({ length: 9 }, (_value, index) => `COM${index + 1}`),
  ...Array.from({ length: 9 }, (_value, index) => `LPT${index + 1}`)
]);

export function sanitizeFilename(filename: string): string {
  const sanitized = filename.replace(invalidFilenameChars, "_").trim().replace(/[. ]+$/g, "").replace(/\s+/g, " ");
  const result = sanitized || "output.pdf";
  const stem = result.includes(".") ? result.replace(/\.[^.]*$/, "") : result;
  if (windowsReservedStems.has(stem.toUpperCase())) {
    return `_${result}`;
  }
  return result;
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
  // trim してから 0 埋めする（Python 側 domain.py の strip と同一の正規化を保つこと）。
  const fixedTokens = fixedTokenPads.map(([key, width]) => padMetadata(String(metadata[key] ?? "").trim(), width));
  fixedTokens.push(padMetadata(String(metadata.seq ?? "").trim(), digits));
  const prefixes = affixTokens(metadata, affixDefs, "prefix");
  const suffixes = affixTokens(metadata, affixDefs, "suffix");
  const tokens = [...prefixes, ...fixedTokens, ...suffixes];
  return sanitizeFilename(`${tokens.join("_")}.pdf`);
}
