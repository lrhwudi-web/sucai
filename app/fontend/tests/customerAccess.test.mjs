import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const superAdminPanel = read("src", "admin", "SuperAdminPanel.tsx");
const adminPanel = read("src", "admin", "AdminPanel.tsx");
const permissionsPanel = read("src", "admin", "PermissionsPanel.tsx");

test("customer visibility rules live in the material admin center", () => {
  assert.match(adminPanel, /CustomerAccessWorkspace/);
  assert.match(adminPanel, /section === "permissions"/);
});

test("super admin center does not duplicate customer visibility rules", () => {
  assert.doesNotMatch(superAdminPanel, /CustomerAccessWorkspace/);
  assert.doesNotMatch(superAdminPanel, /section === "access"/);
});

test("account permission controls consume backend brand options without global rules", () => {
  assert.match(permissionsPanel, /permissionValues\.brand/);
  assert.match(permissionsPanel, /brandOptions\.map/);
  assert.doesNotMatch(permissionsPanel, /ruleScope/);
});
