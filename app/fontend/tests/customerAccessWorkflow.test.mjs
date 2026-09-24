import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const panel = read("src", "admin", "PermissionsPanel.tsx");
const service = read("src", "admin", "adminService.ts");

test("customer access uses one account workbench instead of stacked account cards", () => {
  assert.match(panel, /customer-access-table/);
  assert.doesNotMatch(panel, /全局隐藏规则/);
  assert.doesNotMatch(panel, /customer-rules-view/);
  assert.match(panel, /搜索姓名或邮箱/);
  assert.doesNotMatch(panel, /permissions-kpis/);
});

test("account creation is a three-step account and permission workflow", () => {
  assert.match(panel, /填写账号/);
  assert.match(panel, /选择权限/);
  assert.match(panel, /确认创建/);
  assert.match(panel, /只开放指定品牌/);
  assert.match(panel, /自定义品牌与扩展素材/);
  assert.match(panel, /开放全部素材/);
  assert.match(panel, /const permissionMode: PermissionMode = "allowlist"/);
  assert.match(panel, /\/api\/admin\/users/);
  assert.match(panel, /permission_scopes/);
  assert.match(panel, /permission_values/);
});

test("customer access loader maps the persisted permission mode", () => {
  assert.match(service, /permission_mode/);
  assert.match(service, /permissionMode: user\.permission_mode === "allowlist"/);
});

test("super administrators can filter customer accounts by salesperson without reloading", () => {
  assert.match(panel, /aria-label="筛选业务员"/);
  assert.match(panel, /全部业务员/);
  assert.match(panel, /salespersonFilter/);
  assert.match(panel, /createdByUserId/);
  assert.match(panel, /isSuperAdmin &&/);
  assert.match(service, /salespeople: \(payload\.salespeople \|\| \[\]\)\.map/);
  assert.match(service, /created_by_user_id/);
});

test("new customer accounts reset the salesperson filter and refresh the visible count", () => {
  const workspace = read("src", "admin", "CustomerAccessWorkspace.tsx");
  const adminPanel = read("src", "admin", "AdminPanel.tsx");
  assert.match(panel, /setSalespersonFilter\("all"\);\s*await onRefresh\(\)/);
  assert.match(workspace, /onCustomerCountChange\?\.\(overview\.users\.length\)/);
  assert.match(adminPanel, /onCustomerCountChange=\{setCustomerCount\}/);
  assert.match(adminPanel, /overview\?\.users\.length \?\? customerCount/);
});

test("customer accounts show the fifteen-day expiry policy", () => {
  assert.match(service, /expires_at/);
  assert.match(panel, /有效期至/);
  assert.match(panel, /创建后 15 天自动停用/);
});

test("collapsed permission chips reveal remaining values on hover and keyboard focus", () => {
  assert.match(panel, /PermissionOverflow/);
  assert.match(panel, /permission-overflow-tooltip/);
  assert.match(panel, /onMouseEnter/);
  assert.match(panel, /onFocus/);
});

test("account editor handles status, full permissions, and safe password reset", () => {
  assert.match(panel, /编辑客户账号/);
  assert.match(panel, /停用此账号/);
  assert.match(panel, /重置临时密码/);
  assert.match(panel, /原密码经过加密哈希保存，无法查看/);
  assert.match(panel, /\/api\/admin\/users\/\$\{editingUser\.id\}/);
  assert.match(panel, /reset-password/);
});

test("account editor preserves effective permissions while switching permission modes", () => {
  assert.match(panel, /const effectiveBrands = visibleBrandsFor\(user\)/);
  assert.match(panel, /setEditSelectedBrands\(effectiveBrands\)/);
  assert.match(panel, /switchEditPermissionPreset/);
  assert.doesNotMatch(panel, /switchEditPermissionPreset[\s\S]{0,500}setEditSelectedBrands\(\[\]\)/);
  assert.doesNotMatch(panel, /switchEditPermissionPreset[\s\S]{0,500}setEditSelectedOther\(\[\]\)/);
});

test("permission scope aliases remain compatible with persisted grants", () => {
  assert.match(panel, /function normalizeScope/);
  assert.match(panel, /normalizeScope\(scope\)/);
  assert.match(panel, /normalizeScope\(alias\)/);
  assert.doesNotMatch(panel, /hiddenOtherForRole/);
});

test("wizard errors remain readable above the modal backdrop", () => {
  assert.match(panel, /permission-error-banner/);
  assert.match(panel, /role="alert"/);
});
