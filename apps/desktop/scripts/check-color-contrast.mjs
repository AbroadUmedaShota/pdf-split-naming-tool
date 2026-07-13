import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(__dirname, "..", "app", "globals.css"), "utf8");
const foregroundTokens = ["muted", "subtle"];
const backgroundTokens = ["surface", "surface-2", "bg", "surface-3"];
const minimumRatio = 4.5;

function tokenColor(name) {
  const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`));
  assert(match, `CSS color token --${name} was not found`);
  return match[1];
}

function relativeLuminance(hex) {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    .map((channel) => Number.parseInt(channel, 16) / 255)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(foreground, background) {
  const luminances = [relativeLuminance(foreground), relativeLuminance(background)].sort((a, b) => b - a);
  return (luminances[0] + 0.05) / (luminances[1] + 0.05);
}

const results = [];
for (const foregroundToken of foregroundTokens) {
  for (const backgroundToken of backgroundTokens) {
    const foreground = tokenColor(foregroundToken);
    const background = tokenColor(backgroundToken);
    const ratio = contrastRatio(foreground, background);
    results.push({ backgroundToken, foregroundToken, ratio });
    assert(
      ratio >= minimumRatio,
      `--${foregroundToken} on --${backgroundToken} is ${ratio.toFixed(2)}:1; expected at least ${minimumRatio}:1`,
    );
  }
}

console.log(
  `[test:color-contrast] ${results.map(({ backgroundToken, foregroundToken, ratio }) => `--${foregroundToken}/--${backgroundToken}=${ratio.toFixed(2)}:1`).join(", ")}`,
);
