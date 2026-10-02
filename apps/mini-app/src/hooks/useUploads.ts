import { useSyncExternalStore } from "react";
import { uploads, type UploadView } from "../services/uploader";

export function useUploads(projectId?: string): UploadView[] {
  const all = useSyncExternalStore(uploads.subscribe, uploads.getSnapshot);
  return projectId ? all.filter((u) => u.projectId === projectId) : all;
}
