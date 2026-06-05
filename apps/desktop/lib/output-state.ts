import type { SidecarOutputCheck, SidecarOutputItem } from "./sidecar";

export type OutputCheckLike = SidecarOutputCheck | SidecarOutputItem;

function isExportItem(check: OutputCheckLike): check is SidecarOutputItem {
  return "status" in check;
}

export function isOutputCheckOk(check: OutputCheckLike): boolean {
  return check.ok && (!isExportItem(check) || check.status !== "failed");
}

export function outputIssueCount(checks: OutputCheckLike[]): number {
  return checks.filter((check) => !isOutputCheckOk(check)).length;
}

export function outputListStateText(check: OutputCheckLike): string {
  if (isOutputCheckOk(check)) {
    return check.has_existing_output ? "既存あり" : "出力可能";
  }
  return isExportItem(check) && check.status === "failed" ? "出力失敗" : "要修正";
}

export function outputDetailStateText(check: OutputCheckLike): string {
  if (isOutputCheckOk(check)) {
    return "出力可能";
  }
  if (isExportItem(check) && check.status === "failed") {
    return check.error || check.messages.join(" / ") || "出力失敗";
  }
  return check.messages.join(" / ");
}
