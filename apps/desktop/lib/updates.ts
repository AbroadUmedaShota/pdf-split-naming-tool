import { getVersion } from "@tauri-apps/api/app";
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type DownloadEvent, type Update } from "@tauri-apps/plugin-updater";

export type AppUpdate = Update;

export type UpdateInstallProgress = {
  downloadedBytes: number;
  contentLength?: number;
  finished: boolean;
};

export async function readCurrentVersion(): Promise<string> {
  return getVersion();
}

export async function checkForAppUpdate(): Promise<AppUpdate | null> {
  return check({ timeout: 30000 });
}

export async function installAppUpdate(
  update: AppUpdate,
  onProgress?: (progress: UpdateInstallProgress) => void
): Promise<void> {
  let downloadedBytes = 0;
  let contentLength: number | undefined;

  await update.downloadAndInstall((event: DownloadEvent) => {
    if (event.event === "Started") {
      downloadedBytes = 0;
      contentLength = event.data.contentLength;
      onProgress?.({ downloadedBytes, contentLength, finished: false });
      return;
    }
    if (event.event === "Progress") {
      downloadedBytes += event.data.chunkLength;
      onProgress?.({ downloadedBytes, contentLength, finished: false });
      return;
    }
    onProgress?.({ downloadedBytes, contentLength, finished: true });
  });

  await relaunch();
}

export function updateErrorMessage(error: unknown): string {
  const message = String(error);
  if (message.includes("invoke") || message.includes("__TAURI__") || message.includes("not allowed")) {
    return "更新確認はデスクトップアプリで利用できます。";
  }
  return message;
}
