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
  const big = (seed: number, size = 3 * 1024 * 1024): Uint8Array<ArrayBuffer> =>
    new Uint8Array(new ArrayBuffer(size)).map((_, i) => (i * 7 + seed) & 0xff);

  it("follows the content, not the name or timestamp the picker invents", async () => {
    const a = new File([big(1)], "copy_0842-A.mov", { lastModified: 1_759_000_000_000 });
    const b = new File([big(1)], "copy_77F1-B.mov", { lastModified: 1_759_999_999_999 });
    expect(await fileFingerprint(a)).toBe(await fileFingerprint(b));
    expect(await fileFingerprint(a)).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it("differs when the head, the tail or the size differ", async () => {
    const base = big(1);
    const tailChanged = base.slice();
    tailChanged[tailChanged.length - 1] = (base[base.length - 1] ?? 0) ^ 0xff;
    const fp = (bytes: Uint8Array<ArrayBuffer>) => fileFingerprint(new File([bytes], "x.mov"));
    const reference = await fp(base);
    expect(await fp(big(2))).not.toBe(reference);
    expect(await fp(tailChanged)).not.toBe(reference);
    expect(await fp(base.slice(0, base.length - 1))).not.toBe(reference);
    expect(await fp(new Uint8Array(new ArrayBuffer(3)))).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });
});
