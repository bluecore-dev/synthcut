import { describe, expect, it } from "vitest";
import { fileFingerprint, md5Part } from "./hashing";

const bytes = (s: string) => new TextEncoder().encode(s).buffer as ArrayBuffer;

describe("md5Part", () => {
  it("matches RFC 1321 vectors in hex and Content-MD5 base64", async () => {
    expect(await md5Part(bytes(""))).toEqual({ hex: "d41d8cd98f00b204e9800998ecf8427e", b64: "1B2M2Y8AsgTpgAmY7PhCfg==" });
    expect((await md5Part(bytes("abc"))).hex).toBe("900150983cd24fb0d6963f7d28e17f72");
  });

  it("hashes binary data larger than one MD5 block", async () => {
    const buf = new Uint8Array(1_000_003).map((_, i) => (i * 31) & 0xff).buffer;
    const { hex, b64 } = await md5Part(buf);
    expect(hex).toMatch(/^[0-9a-f]{32}$/);
    expect(atob(b64).length).toBe(16);
  });
});

describe("fileFingerprint", () => {
  it("is stable for the same file and URL-safe", async () => {
    const a = new File(["x"], "clip.mov", { lastModified: 1_759_000_000_000 });
    const b = new File(["y"], "clip.mov", { lastModified: 1_759_000_000_000 });
    const c = new File(["x"], "clip.mov", { lastModified: 1_759_000_000_001 });
    expect(await fileFingerprint(a)).toBe(await fileFingerprint(b));
    expect(await fileFingerprint(a)).not.toBe(await fileFingerprint(c));
    expect(await fileFingerprint(a)).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });
});
