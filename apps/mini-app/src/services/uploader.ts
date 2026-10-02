// Resumable, verified, direct-to-storage uploads (spec §6, §49).
//
// For every part: read the slice → MD5 → ask the API for a URL whose
// signature covers that MD5 → PUT the bytes straight to storage → check the
// returned ETag. Storage itself rejects a body that differs from the signed
// MD5, so a corrupted part can never be stored. Files upload one after
// another, three parts at a time; a failed part retries with backoff, and a
// lost network pauses the file until the browser is online again.

import { ApiError, api, unwrap, type UploadSessionOut } from "../api/client";
import { haptic, setClosingConfirmation } from "../telegram";
import { fileFingerprint, md5Part } from "./hashing";

export type UploadPhase =
  | "queued"
  | "preparing"
  | "verifying"
  | "uploading"
  | "paused"
  | "offline"
  | "completing"
  | "done"
  | "duplicate"
  | "error"
  | "cancelled";

export interface UploadView {
  id: string;
  projectId: string;
  name: string;
  size: number;
  phase: UploadPhase;
  uploaded: number;
  speed: number;
  partCount: number;
  partsDone: number;
  sessionId?: string;
  assetId?: string;
  resumed: boolean;
  error?: string;
}

interface UploadItem extends UploadView {
  file: File;
  partSize: number;
  done: Set<number>;
  inflight: Map<number, number>;
  verifiedBytes: number;
  lastSample: { at: number; bytes: number };
  /** Last failure not yet reported to the server (shown in the project log). */
  pendingError?: string;
}

const PARALLEL_PARTS = 3;
const MAX_PART_ATTEMPTS = 6;
const PROGRESS_REPORT_MS = 4000;

class Paused extends Error {}

class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitOnline = () =>
  navigator.onLine ? Promise.resolve() : new Promise<void>((r) => window.addEventListener("online", () => r(), { once: true }));

let localSeq = 0;

export class UploadManager {
  private items: UploadItem[] = [];
  private listeners = new Set<() => void>();
  private snapshot: UploadView[] = [];
  private emitTimer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private xhrs = new Map<string, Set<XMLHttpRequest>>();
  private wakeLock: { release(): Promise<void> } | null = null;
  /** Called when a project's server-side assets changed (refresh queries). */
  onAssetsChanged: (projectId: string) => void = () => {};

  constructor() {
    window.addEventListener("online", () => {
      for (const item of this.items) if (item.phase === "offline") item.phase = "queued";
      this.emit();
      void this.pump();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && this.running) void this.acquireWakeLock();
    });
    setInterval(() => this.sampleSpeed(), 1000);
  }

  // ------------------------------------------------------------------ store API

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = () => this.snapshot;

  private emit(now = true) {
    const flush = () => {
      this.emitTimer = null;
      this.snapshot = this.items.map((i) => ({
        id: i.id,
        projectId: i.projectId,
        name: i.name,
        size: i.size,
        phase: i.phase,
        uploaded: Math.min(i.size, i.verifiedBytes + [...i.inflight.values()].reduce((a, b) => a + b, 0)),
        speed: i.speed,
        partCount: i.partCount,
        partsDone: i.done.size,
        sessionId: i.sessionId,
        assetId: i.assetId,
        resumed: i.resumed,
        error: i.error,
      }));
      for (const l of this.listeners) l();
    };
    if (now) {
      if (this.emitTimer) clearTimeout(this.emitTimer);
      flush();
    } else if (!this.emitTimer) {
      this.emitTimer = setTimeout(flush, 200);
    }
  }

  // ------------------------------------------------------------------ commands

  add(projectId: string, files: File[]) {
    for (const file of files) {
      this.items.push({
        id: `u${++localSeq}`,
        projectId,
        file,
        name: file.name,
        size: file.size,
        phase: "queued",
        uploaded: 0,
        speed: 0,
        partCount: 0,
        partsDone: 0,
        partSize: 0,
        resumed: false,
        done: new Set(),
        inflight: new Map(),
        verifiedBytes: 0,
        lastSample: { at: Date.now(), bytes: 0 },
      });
    }
    this.emit();
    void this.pump();
  }

  pause(id: string) {
    const item = this.find(id);
    if (!item || !["queued", "preparing", "verifying", "uploading", "offline"].includes(item.phase)) return;
    item.phase = "paused";
    this.abortRequests(item);
    this.emit();
  }

  resume(id: string) {
    const item = this.find(id);
    if (!item || !["paused", "error", "offline"].includes(item.phase)) return;
    item.phase = "queued";
    item.error = undefined;
    this.emit();
    void this.pump();
  }

  async cancel(id: string) {
    const item = this.find(id);
    if (!item || ["done", "cancelled", "duplicate"].includes(item.phase)) return;
    item.phase = "cancelled";
    this.abortRequests(item);
    this.emit();
    if (item.sessionId) {
      try {
        await unwrap(api.DELETE("/api/v1/uploads/{session_id}", { params: { path: { session_id: item.sessionId } } }));
      } catch {
        /* the server-side expiry job cleans up anyway */
      }
      this.onAssetsChanged(item.projectId);
    }
  }

  dismiss(id: string) {
    this.items = this.items.filter((i) => i.id !== id || !["done", "cancelled", "duplicate"].includes(i.phase));
    this.emit();
  }

  hasActive(projectId?: string) {
    return this.items.some(
      (i) => (!projectId || i.projectId === projectId) && !["done", "cancelled", "duplicate", "error", "paused"].includes(i.phase),
    );
  }

  private find(id: string) {
    return this.items.find((i) => i.id === id);
  }

  private abortRequests(item: UploadItem) {
    for (const xhr of this.xhrs.get(item.id) ?? []) xhr.abort();
    this.xhrs.delete(item.id);
    item.inflight.clear();
  }

  // ------------------------------------------------------------------ scheduling

  private async pump() {
    if (this.running) return;
    const next = this.items.find((i) => i.phase === "queued");
    if (!next) {
      setClosingConfirmation(false);
      void this.releaseWakeLock();
      return;
    }
    this.running = true;
    setClosingConfirmation(true);
    void this.acquireWakeLock();
    try {
      await this.process(next);
    } finally {
      this.running = false;
      void this.pump();
    }
  }

  private async process(item: UploadItem) {
    try {
      item.phase = "preparing";
      this.emit();
      const fingerprint = await fileFingerprint(item.file);
      let session = await this.openSession(item, fingerprint);
      if (!session) return;

      if (session.resumed && session.uploaded_parts.length) {
        item.phase = "verifying";
        this.emit();
        if (!(await this.sampleMatches(item, session))) {
          // Same name and size but different bytes: never stitch two files together.
          await unwrap(api.DELETE("/api/v1/uploads/{session_id}", { params: { path: { session_id: session.id } } }));
          session = await this.openSession(item, fingerprint);
          if (!session) return;
        }
      }
      this.applySession(item, session);
      if (this.stopped(item)) return;

      item.phase = "uploading";
      this.emit();
      await this.uploadMissing(item);
      if (this.stopped(item)) return;

      item.phase = "completing";
      this.emit();
      await this.complete(item);
      item.phase = "done";
      haptic.success();
      this.onAssetsChanged(item.projectId);
    } catch (err) {
      if (err instanceof Paused || this.stopped(item)) return;
      if (!navigator.onLine) {
        item.phase = "offline";
      } else {
        item.phase = "error";
        item.error = err instanceof Error ? err.message : String(err);
        haptic.error();
      }
      item.pendingError = `${item.phase === "offline" ? "internet yo'q" : "to'xtadi"}: ${item.error ?? ""}`.slice(0, 300);
      void this.reportProgress(item, true);
    } finally {
      item.inflight.clear();
      this.emit();
    }
  }

  private stopped(item: UploadItem) {
    return item.phase === "paused" || item.phase === "cancelled";
  }

  private async openSession(item: UploadItem, fingerprint: string): Promise<UploadSessionOut | null> {
    try {
      return await unwrap(
        api.POST("/api/v1/projects/{project_id}/uploads", {
          params: { path: { project_id: item.projectId } },
          body: {
            filename: item.file.name,
            size_bytes: item.file.size,
            content_type: item.file.type || "application/octet-stream",
            last_modified_ms: item.file.lastModified || null,
            fingerprint,
          },
        }),
      );
    } catch (err) {
      if (err instanceof ApiError && err.code === "already_uploaded") {
        item.phase = "duplicate";
        return null;
      }
      throw err;
    }
  }

  private applySession(item: UploadItem, session: UploadSessionOut) {
    item.sessionId = session.id;
    item.assetId = session.asset_id;
    item.partSize = session.part_size;
    item.partCount = session.part_count;
    item.resumed = !!session.resumed;
    item.done = new Set(session.uploaded_parts.map((p) => p.number));
    item.verifiedBytes = session.uploaded_parts.reduce((sum, p) => sum + p.size, 0);
    item.lastSample = { at: Date.now(), bytes: item.verifiedBytes };
    this.onAssetsChanged(item.projectId);
  }

  private async sampleMatches(item: UploadItem, session: UploadSessionOut): Promise<boolean> {
    const parts = session.uploaded_parts;
    const picks = [parts[0], parts[Math.floor(parts.length / 2)], parts[parts.length - 1]];
    const seen = new Set<number>();
    for (const part of picks) {
      if (!part || seen.has(part.number)) continue;
      seen.add(part.number);
      const start = (part.number - 1) * session.part_size;
      const buf = await item.file.slice(start, start + session.part_size).arrayBuffer();
      if (buf.byteLength !== part.size) return false;
      const { hex } = await md5Part(buf);
      if (hex !== part.etag.toLowerCase()) return false;
    }
    return true;
  }

  // ------------------------------------------------------------------ parts

  private async uploadMissing(item: UploadItem) {
    const queue: number[] = [];
    for (let n = 1; n <= item.partCount; n++) if (!item.done.has(n)) queue.push(n);
    const reporter = setInterval(() => void this.reportProgress(item), PROGRESS_REPORT_MS);
    try {
      const workers = Array.from({ length: Math.min(PARALLEL_PARTS, queue.length) }, async () => {
        while (queue.length && item.phase === "uploading") {
          await this.uploadPart(item, queue.shift()!);
        }
      });
      await Promise.all(workers);
    } finally {
      clearInterval(reporter);
    }
    void this.reportProgress(item);
  }

  private async uploadPart(item: UploadItem, n: number) {
    const start = (n - 1) * item.partSize;
    const buf = await item.file.slice(start, Math.min(start + item.partSize, item.size)).arrayBuffer();
    const { hex, b64 } = await md5Part(buf);
    for (let attempt = 1; ; attempt++) {
      if (item.phase !== "uploading") throw new Paused();
      try {
        const signed = await unwrap(
          api.POST("/api/v1/uploads/{session_id}/parts", {
            params: { path: { session_id: item.sessionId! } },
            body: { parts: [{ number: n, md5_b64: b64 }] },
          }),
        );
        const part = signed.parts[0]!;
        const etag = await this.put(item, n, part.url, part.headers, buf);
        if (etag && etag !== hex) throw new Error(`ETag mos kelmadi (qism ${n})`);
        item.inflight.delete(n);
        item.done.add(n);
        item.verifiedBytes += buf.byteLength;
        this.emit(false);
        return;
      } catch (err) {
        item.inflight.delete(n);
        if (err instanceof Paused || item.phase !== "uploading") throw new Paused();
        item.pendingError = `qism ${n}, urinish ${attempt}: ${err instanceof Error ? err.message : String(err)}`.slice(0, 300);
        void this.reportProgress(item);
        if (err instanceof ApiError && err.status >= 400 && err.status < 500 && err.status !== 429) throw err;
        if (attempt >= MAX_PART_ATTEMPTS) throw err;
        await waitOnline();
        await sleep(Math.min(30_000, 1000 * 2 ** (attempt - 1)));
      }
    }
  }

  private put(item: UploadItem, n: number, url: string, headers: Record<string, string>, body: ArrayBuffer) {
    return new Promise<string | null>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const set = this.xhrs.get(item.id) ?? new Set();
      set.add(xhr);
      this.xhrs.set(item.id, set);
      const untrack = () => set.delete(xhr);
      xhr.open("PUT", url);
      for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
      xhr.timeout = 10 * 60 * 1000;
      xhr.upload.onprogress = (e) => {
        item.inflight.set(n, e.loaded);
        this.emit(false);
      };
      xhr.onload = () => {
        untrack();
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve((xhr.getResponseHeader("ETag") ?? "").replace(/"/g, "").toLowerCase() || null);
        } else {
          reject(new HttpError(xhr.status, `Storage ${xhr.status}: ${xhr.responseText.slice(0, 120)}`));
        }
      };
      xhr.onerror = () => {
        untrack();
        reject(new HttpError(0, "Tarmoq uzildi"));
      };
      xhr.ontimeout = () => {
        untrack();
        reject(new HttpError(0, "Vaqt tugadi"));
      };
      xhr.onabort = () => {
        untrack();
        reject(new Paused());
      };
      xhr.send(body);
    });
  }

  private async complete(item: UploadItem) {
    for (let round = 0; ; round++) {
      try {
        await unwrap(
          api.POST("/api/v1/uploads/{session_id}/complete", { params: { path: { session_id: item.sessionId! } } }),
        );
        return;
      } catch (err) {
        if (!(err instanceof ApiError) || err.code !== "upload_incomplete" || round >= 1) throw err;
        // Storage is missing parts we thought were stored: upload them again.
        const state = await unwrap(
          api.GET("/api/v1/uploads/{session_id}", { params: { path: { session_id: item.sessionId! } } }),
        );
        item.done = new Set(state.uploaded_parts.map((p) => p.number));
        item.verifiedBytes = state.uploaded_parts.reduce((s, p) => s + p.size, 0);
        item.phase = "uploading";
        await this.uploadMissing(item);
        item.phase = "completing";
      }
    }
  }

  private async reportProgress(item: UploadItem, force = false) {
    if (!item.sessionId) return;
    const error = item.pendingError;
    if (item.phase !== "uploading" && !error && !force) return;
    item.pendingError = undefined;
    const bytes = item.verifiedBytes + [...item.inflight.values()].reduce((a, b) => a + b, 0);
    try {
      await unwrap(
        api.POST("/api/v1/uploads/{session_id}/progress", {
          params: { path: { session_id: item.sessionId } },
          body: { bytes_uploaded: bytes, error: error ?? null },
        }),
      );
    } catch {
      /* progress reports are best effort */
    }
  }

  private sampleSpeed() {
    let changed = false;
    for (const item of this.items) {
      if (item.phase !== "uploading") {
        if (item.speed) {
          item.speed = 0;
          changed = true;
        }
        continue;
      }
      const now = Date.now();
      const bytes = item.verifiedBytes + [...item.inflight.values()].reduce((a, b) => a + b, 0);
      const dt = (now - item.lastSample.at) / 1000;
      if (dt > 0) {
        const instant = Math.max(0, bytes - item.lastSample.bytes) / dt;
        item.speed = item.speed ? item.speed * 0.75 + instant * 0.25 : instant;
        item.lastSample = { at: now, bytes };
        changed = true;
      }
    }
    if (changed) this.emit(false);
  }

  private async acquireWakeLock() {
    try {
      const nav = navigator as Navigator & { wakeLock?: { request(type: "screen"): Promise<{ release(): Promise<void> }> } };
      if (nav.wakeLock && !this.wakeLock) this.wakeLock = await nav.wakeLock.request("screen");
    } catch {
      /* not supported in this WebView */
    }
  }

  private async releaseWakeLock() {
    try {
      await this.wakeLock?.release();
    } catch {
      /* ignore */
    }
    this.wakeLock = null;
  }
}

export const uploads = new UploadManager();
