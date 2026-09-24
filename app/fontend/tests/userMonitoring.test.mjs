import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const superAdminPanel = read("src", "admin", "SuperAdminPanel.tsx");
const monitor = read("src", "admin", "UserMonitorWorkspace.tsx");
const service = read("src", "admin", "superAdminService.ts");
const drawer = read("src", "components", "ProductDrawer.tsx");
const materials = read("src", "services", "materials.ts");

test("super admin exposes a separate user monitoring section", () => {
  assert.match(superAdminPanel, /用户监控/);
  assert.match(superAdminPanel, /UserMonitorWorkspace/);
  assert.match(superAdminPanel, /section === "monitor"/);
});

test("monitor describes every recorded activity type", () => {
  assert.match(monitor, /登录系统/);
  assert.match(monitor, /查看原图/);
  assert.match(monitor, /下载素材/);
  assert.match(monitor, /打开 Drive 素材/);
});

test("user monitoring requests are restricted to super admin endpoints", () => {
  assert.match(service, /\/api\/super-admin\/user-monitor/);
  assert.doesNotMatch(service, /\/api\/admin\/user-monitor/);
});

test("opening an original records the selected asset without blocking preview", () => {
  assert.match(drawer, /recordOriginalOpen\(product\.sku, selectedAsset\.id\)/);
  assert.match(drawer, /catch\(\(\) => undefined\)/);
  assert.match(materials, /\/api\/activity\/original-open/);
});
