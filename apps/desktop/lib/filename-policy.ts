const requiredMetadata = ["box_no", "binder_no", "seq"] as const;
const invalidFilenameChars = /[<>:"/\\|?*]/g;

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

export function previewFilename(metadata: Record<string, string>): string {
  if (missingMetadata(metadata).length) {
    return "未入力";
  }
  return sanitizeFilename(
    `${padMetadata(metadata.box_no ?? "", 2)}_${padMetadata(metadata.binder_no ?? "", 2)}_${padMetadata(
      metadata.seq ?? "",
      3
    )}.pdf`
  );
}
