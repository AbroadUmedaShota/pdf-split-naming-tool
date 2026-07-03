import type { SidecarExportResponse, SidecarOutputCheck, SidecarOutputItem } from "./sidecar";

export type OutputCheckLike = SidecarOutputCheck | SidecarOutputItem;

function isExportItem(check: OutputCheckLike): check is SidecarOutputItem {
  return "status" in check;
}

export function isOutputCheckOk(check: OutputCheckLike): boolean {
  return check.ok && (!isExportItem(check) || check.status !== "failed");
}

// 出力実行が完了し、このファイルが実際に作成済みの行か。
// 出力前チェック段階の ok 行（まだ未出力）と区別し、完了を可視化するための判定。
export function isOutputItemCreated(check: OutputCheckLike): boolean {
  return isExportItem(check) && check.status === "created";
}

// バッチ内で同名のファイル名が要求され、予約採番（_2 など）で別名に変わった行か。
// ok のまま黙って別名出力される行をユーザーへ可視化するための判定。
export function isOutputCheckRenamed(check: OutputCheckLike): boolean {
  return Boolean(check.filename) && Boolean(check.requested_filename) && check.filename !== check.requested_filename;
}

export function outputIssueCount(checks: OutputCheckLike[]): number {
  return checks.filter((check) => !isOutputCheckOk(check)).length;
}

// ユーザーが上書きを許可し、同名の既存ファイルを置き換えて出力する行か。
export function isOutputCheckOverwrite(check: OutputCheckLike): boolean {
  return Boolean(check.will_overwrite);
}

// 未解消の既存衝突（上書き許可されていない、出力をブロックする既存ファイル）の件数。
export function unresolvedExistingCount(checks: OutputCheckLike[]): number {
  return checks.filter((check) => check.has_existing_output && !check.will_overwrite).length;
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
  if (msg === "output_path_too_long") {
    return "出力パスが長すぎます（260文字以内に収まるよう出力先を浅くするか項目を短くしてください）";
  }
  if (msg === "output_will_overwrite") {
    return "同名の既存ファイルを上書きします";
  }
  if (msg === "duplicate_output_in_batch") {
    return "バッチ内で同じ出力名が重複しています。連番を修正してください";
  }
  return msg;
}

export function outputListStateText(check: OutputCheckLike): string {
  if (isOutputItemCreated(check)) {
    if (isOutputCheckOverwrite(check)) {
      return "上書き出力済み";
    }
    return isOutputCheckRenamed(check) ? "作成済み（別名採番）" : "作成済み";
  }
  if (isOutputCheckOk(check)) {
    if (isOutputCheckOverwrite(check)) {
      return "上書きして出力";
    }
    return isOutputCheckRenamed(check) ? "同名のため別名採番" : "出力可能";
  }
  if (check.has_existing_output) {
    return "既存あり（要対処）";
  }
  return isExportItem(check) && check.status === "failed" ? "出力失敗" : "要修正";
}

export function outputDetailStateText(check: OutputCheckLike): string {
  if (isOutputItemCreated(check)) {
    if (isOutputCheckOverwrite(check)) {
      return `同名の既存ファイルを上書きして出力済み（${check.filename}）`;
    }
    return isOutputCheckRenamed(check) ? `作成済み（別名「${check.filename}」で採番）` : "作成済み";
  }
  if (isOutputCheckOk(check)) {
    if (isOutputCheckOverwrite(check)) {
      return "同名の既存ファイルを上書きして出力します";
    }
    return isOutputCheckRenamed(check) ? `バッチ内で同名のため「${check.filename}」を採番` : "出力可能";
  }
  if (isExportItem(check) && check.status === "failed") {
    return check.error || check.messages.map(formatMessage).join(" / ") || "出力失敗";
  }
  return check.messages.map(formatMessage).join(" / ");
}

// 「失敗分のみ再出力」の結果を元の出力結果へマージする。
// base.items は初回出力の全行、retry.items は失敗indexのみを再出力した結果（failedIndices と同順）。
// 成功済み行は温存し、失敗していた位置だけ retry の結果で差し替え、サマリ・ok・messages を再計算する。
export function mergeRetriedExport(
  base: SidecarExportResponse,
  retry: SidecarExportResponse,
  failedIndices: number[]
): SidecarExportResponse {
  const mergedItems = [...base.items];
  failedIndices.forEach((originalIndex, retryIndex) => {
    const retried = retry.items[retryIndex];
    if (retried) {
      mergedItems[originalIndex] = retried;
    }
  });
  const created = mergedItems.filter((item) => isOutputItemCreated(item)).length;
  const failed = mergedItems.filter((item) => item.status === "failed").length;
  return {
    ...retry,
    ok: failed === 0,
    output_dir: base.output_dir,
    summary: { created, failed },
    items: mergedItems,
    // 一部成功・一部失敗のときだけ「出力フォルダが不完全」の警告を残す。
    messages: failed > 0 && created > 0 ? ["export_incomplete"] : []
  };
}
