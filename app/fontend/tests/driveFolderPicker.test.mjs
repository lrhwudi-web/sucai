import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const styles = fs.readFileSync(path.join(root, "src", "styles.css"), "utf8");

test("Drive directory selection uses readable type", () => {
  assert.match(styles, /\.folder-selected-value > span \{[\s\S]*?font-size: 12px;/);
  assert.match(styles, /\.folder-selected-value > strong \{[\s\S]*?font-size: 12px;/);
  assert.match(styles, /\.folder-breadcrumbs button \{[\s\S]*?font-size: 11px;/);
  assert.match(styles, /\.folder-option span,[\s\S]*?font-size: 12px;/);
});
