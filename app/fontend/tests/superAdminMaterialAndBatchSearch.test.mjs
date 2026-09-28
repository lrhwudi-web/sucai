import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const app = read("src", "App.tsx");
const adminPanel = read("src", "admin", "AdminPanel.tsx");
const superAdminPanel = read("src", "admin", "SuperAdminPanel.tsx");
const superAdminService = read("src", "admin", "superAdminService.ts");
const materials = read("src", "services", "materials.ts");
const workbook = read("src", "quotation", "WorkbookSheet.tsx");

test("ordinary admins receive the scoped customer-management workspace", () => {
  assert.match(app, /<AdminPanel user=\{currentUser\} search=\{search\} onNotify=\{setToast\} customerOnly \/>/);
  assert.match(adminPanel, /customerOnly \? \(/);
  assert.match(adminPanel, /<CustomerAccessWorkspace/);
  assert.match(adminPanel, /<OrdersPanel user=\{user\}/);
});

test("the full material backend is nested under super admin", () => {
  assert.match(superAdminPanel, /<AdminPanel user=\{user\} search="" onNotify=\{onNotify\}/);
  assert.match(superAdminPanel, />素材管理</);
});

test("organization data uses browser cache and refreshes only by explicit POST", () => {
  assert.match(superAdminService, /localStorage\.getItem\(ORGANIZATION_CACHE_KEY\)/);
  assert.match(superAdminService, /organization\/refresh/);
  assert.match(superAdminService, /method: refresh \? "POST" : "GET"/);
  assert.match(superAdminPanel, /onClick=\{\(\) => refresh\(true\)\}/);
});

test("batch search waits for the full catalogue and reports a compact missing-SKU result", () => {
  assert.match(app, /!catalogueReady/);
  assert.match(app, /reportMissingSkus\(batchMissingSkus, parsedSearch\.skuOrder\.length\)/);
  assert.match(app, /未搜索到的.*已发送给.*添加/);
  assert.match(app, /parsedSearch\.isBatchSkuSearch[\s\S]*?`批量搜索 \$\{parsedSearch\.skuOrder\.length\} 个 SKU/);
  assert.match(materials, /\/api\/catalogue\/missing-skus/);
});

test("administrator Excel imports show and report missing SKUs", () => {
  assert.match(workbook, /管理员 Excel 导入摘要/);
  assert.match(workbook, /查看未找到的 SKU/);
  assert.match(workbook, /reportMissingSkus\(result\.missingSkus,result\.searched,"excel_import"\)/);
  assert.match(workbook, /未搜索到的已发送给管理员添加/);
  assert.match(materials, /source: "batch_search" \| "excel_import"/);
});
