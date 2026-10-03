import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema.gen";

export type Schemas = components["schemas"];
export type ProjectOut = Schemas["ProjectOut"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type StageOut = Schemas["StageOut"];
export type AssetOut = Schemas["AssetOut"];
export type AssetDetail = Schemas["AssetDetail"];
export type MediaInfo = Schemas["MediaInfo"];
export type EventEnvelope = Schemas["EventEnvelope"];
export type JobOut = Schemas["JobOut"];
export type MeOut = Schemas["MeOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type UploadSessionOut = Schemas["UploadSessionOut"];
export type PresetId = Schemas["ProjectPreset"];

const STORAGE_KEY = "synthcut.token";

let token: string | null = null;
let expiresAt = 0;

try {
  const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "null") as { t: string; e: number } | null;
  if (saved && saved.e > Date.now() + 60_000) {
    token = saved.t;
    expiresAt = saved.e;
  }
} catch {
  /* storage unavailable: the app simply re-authenticates */
}

export function setToken(value: string, expires: string): void {
  token = value;
  expiresAt = Date.parse(expires);
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ t: value, e: expiresAt }));
  } catch {
    /* ignore */
  }
}

export function clearToken(): void {
  token = null;
  expiresAt = 0;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export const currentToken = () => token;
export const tokenExpiresAt = () => expiresAt;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(authMiddleware);

type Result<T> = { data?: T; error?: unknown; response: Response };

export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch {
    throw new ApiError(0, "network", "Tarmoq bilan aloqa yo'q");
  }
  if (result.response.ok) return result.data as T;
  const body = result.error as { error?: { code?: string; message?: string; details?: unknown } } | undefined;
  throw new ApiError(
    result.response.status,
    body?.error?.code ?? "http_error",
    body?.error?.message ?? `HTTP ${result.response.status}`,
    body?.error?.details,
  );
}
