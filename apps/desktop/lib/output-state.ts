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

export function formatTopLevelMessage(msg: string): string {
  if (msg === "export_incomplete") {
    return "一部のファイルが出力できませんでした。出力フォルダの内容が不完全な可能性があります";
  }
  return msg;
}

function formatMessage(msg: string): string {
  if (msg === "output_exists") {
    return "同名ファイルが既存です。出力先を変更するか既存ファイルを削除してください";
  }
  return msg;
}

export function outputListStateText(check: OutputCheckLike): string {
  if (isOutputCheckOk(check)) {
    return "出力可能";
  }
  if (check.has_existing_output) {
    return "既存あり（要対処）";
  }
  return isExportItem(check) && check.status === "failed" ? "出力失敗" : "要修正";
}

export function outputDetailStateText(check: OutputCheckLike): string {
  if (isOutputCheckOk(check)) {
    return "出力可能";
  }
  if (isExportItem(check) && check.status === "failed") {
    return check.error || check.messages.map(formatMessage).join(" / ") || "出力失敗";
  }
  return check.messages.map(formatMessage).join(" / ");
}
