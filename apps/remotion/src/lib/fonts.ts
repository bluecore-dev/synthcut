// Fonts are bundled (OFL, @fontsource) and loaded through @remotion/fonts,
// which holds the render until they are ready — a frame never shows a
// fallback font. Subsets cover Uzbek Latin (o‘ g‘), Russian and Uzbek
// Cyrillic (Қ Ғ Ҳ Ў live in cyrillic-ext).
import { loadFont } from "@remotion/fonts";
import m600 from "@fontsource/montserrat/files/montserrat-latin-600-normal.woff2";
import m600x from "@fontsource/montserrat/files/montserrat-latin-ext-600-normal.woff2";
import m600c from "@fontsource/montserrat/files/montserrat-cyrillic-600-normal.woff2";
import m600cx from "@fontsource/montserrat/files/montserrat-cyrillic-ext-600-normal.woff2";
import m800 from "@fontsource/montserrat/files/montserrat-latin-800-normal.woff2";
import m800x from "@fontsource/montserrat/files/montserrat-latin-ext-800-normal.woff2";
import m800c from "@fontsource/montserrat/files/montserrat-cyrillic-800-normal.woff2";
import m800cx from "@fontsource/montserrat/files/montserrat-cyrillic-ext-800-normal.woff2";
import m900 from "@fontsource/montserrat/files/montserrat-latin-900-normal.woff2";
import m900x from "@fontsource/montserrat/files/montserrat-latin-ext-900-normal.woff2";
import m900c from "@fontsource/montserrat/files/montserrat-cyrillic-900-normal.woff2";
import m900cx from "@fontsource/montserrat/files/montserrat-cyrillic-ext-900-normal.woff2";
import i500 from "@fontsource/inter/files/inter-latin-500-normal.woff2";
import i500x from "@fontsource/inter/files/inter-latin-ext-500-normal.woff2";
import i500c from "@fontsource/inter/files/inter-cyrillic-500-normal.woff2";
import i700 from "@fontsource/inter/files/inter-latin-700-normal.woff2";
import i700x from "@fontsource/inter/files/inter-latin-ext-700-normal.woff2";
import i700c from "@fontsource/inter/files/inter-cyrillic-700-normal.woff2";

const LATIN = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD";
const LATIN_EXT = "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF";
const CYRILLIC = "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116";
const CYRILLIC_EXT = "U+0460-052F,U+1C80-1C8A,U+20B4,U+2DE0-2DFF,U+A640-A69F,U+FE2E-FE2F";

const faces: [string, string, string, string][] = [
  ["Montserrat", "600", m600, LATIN], ["Montserrat", "600", m600x, LATIN_EXT],
  ["Montserrat", "600", m600c, CYRILLIC], ["Montserrat", "600", m600cx, CYRILLIC_EXT],
  ["Montserrat", "800", m800, LATIN], ["Montserrat", "800", m800x, LATIN_EXT],
  ["Montserrat", "800", m800c, CYRILLIC], ["Montserrat", "800", m800cx, CYRILLIC_EXT],
  ["Montserrat", "900", m900, LATIN], ["Montserrat", "900", m900x, LATIN_EXT],
  ["Montserrat", "900", m900c, CYRILLIC], ["Montserrat", "900", m900cx, CYRILLIC_EXT],
  ["Inter", "500", i500, LATIN], ["Inter", "500", i500x, LATIN_EXT], ["Inter", "500", i500c, CYRILLIC],
  ["Inter", "700", i700, LATIN], ["Inter", "700", i700x, LATIN_EXT], ["Inter", "700", i700c, CYRILLIC],
];

let loaded: Promise<unknown> | null = null;

export function loadFonts(): Promise<unknown> {
  loaded ??= Promise.all(faces.map(([family, weight, url, unicodeRange]) => loadFont({ family, weight, url, unicodeRange })));
  return loaded;
}
