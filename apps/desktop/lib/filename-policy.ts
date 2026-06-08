const requiredMetadata = ["box_no", "binder_no", "seq"] as const;
const invalidFilenameChars = /[<>:"/\\|?*]/g;

// 固定3項目とゼロ埋め桁数。命名はこのトークン列を `_` で連結して生成する。
const fixedTokenPads: ReadonlyArray<readonly [string, number]> = [
  ["box_no", 2],
  ["binder_no", 2],
  ["seq", 3]
];

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

export function previewFilename(metadata: Record<string, string>, affixDefs: ReadonlyArray<AffixDef> = []): string {
  if (missingMetadata(metadata).length) {
    return "未入力";
  }
  const fixedTokens = fixedTokenPads.map(([key, width]) => padMetadata(String(metadata[key] ?? ""), width));
  const prefixes = affixTokens(metadata, affixDefs, "prefix");
  const suffixes = affixTokens(metadata, affixDefs, "suffix");
  const tokens = [...prefixes, ...fixedTokens, ...suffixes];
  return sanitizeFilename(`${tokens.join("_")}.pdf`);
}
