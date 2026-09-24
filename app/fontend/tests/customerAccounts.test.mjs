import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const panel = fs.readFileSync(path.join(root, "src", "admin", "PermissionsPanel.tsx"), "utf8");
const adminPanel = fs.readFileSync(path.join(root, "src", "admin", "AdminPanel.tsx"), "utf8");
const adminNav = fs.readFileSync(path.join(root, "src", "admin", "AdminNav.tsx"), "utf8");
const header = fs.readFileSync(path.join(root, "src", "components", "Header.tsx"), "utf8");
const ordersPanel = fs.readFileSync(path.join(root, "src", "orders", "OrdersPanel.tsx"), "utf8");
const orderService = fs.readFileSync(path.join(root, "src", "orders", "orderService.ts"), "utf8");
const quoteBuilder = fs.readFileSync(path.join(root, "src", "quotation", "QuoteBuilder.tsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src", "styles.css"), "utf8");

test("customer account form exposes only customer roles", () => {
  assert.match(panel, /value="overseas_customer"/);
  assert.match(panel, /value="domestic_customer"/);
  assert.match(panel, /value="service_provider"/);
  assert.doesNotMatch(panel, /value="admin"/);
  assert.doesNotMatch(panel, /value="super_admin"/);
});

test("material admin combines customer accounts and visibility rules", () => {
  assert.match(adminPanel, /CustomerAccessWorkspace/);
  assert.doesNotMatch(adminPanel, /CustomerAccountsPanel/);
  assert.match(adminNav, /客户账号与权限/);
  assert.doesNotMatch(adminNav, /label: "客户账号"/);
});

test("admin customer orders live in the customer-management sidebar", () => {
  assert.match(adminNav, /id: "orders" as const, label: "客户订单"/);
  assert.match(adminPanel, /section === "orders"/);
  assert.match(adminPanel, /<OrdersPanel user=\{user\}/);
  assert.match(header, /!user\.isAdmin/);
  assert.match(header, />\s*My Orders\s*</);
  assert.doesNotMatch(header, /user\.isAdmin \? "客户订单"/);
});

test("admin orders group customers and use a three-pane workbench without the old hero copy", () => {
  assert.match(ordersPanel, /interface CustomerOrderGroup/);
  assert.match(ordersPanel, /orders-customer-pane/);
  assert.match(ordersPanel, /orders-table-pane/);
  assert.match(ordersPanel, /orders-detail-pane/);
  assert.match(ordersPanel, /customerGroups/);
  assert.match(ordersPanel, /user\.isSuperAdmin \? "全部客户" : "我的客户"/);
  assert.doesNotMatch(ordersPanel, /SALES ORDERS/);
  assert.doesNotMatch(ordersPanel, /这里只显示由你创建客户提交的订单/);
});

test("admin orders expose lifecycle status and refresh after an Excel download", () => {
  assert.match(ordersPanel, /全部状态/);
  assert.match(ordersPanel, /新订单/);
  assert.match(ordersPanel, /已确认/);
  assert.match(ordersPanel, /order-status-chip/);
  assert.match(ordersPanel, /handleAdminDownload/);
  assert.match(ordersPanel, /status: "confirmed"/);
  assert.match(ordersPanel, /window\.setTimeout\(load, 900\)/);
});

test("customer orders use a monthly two-pane workspace with persistent details", () => {
  assert.match(ordersPanel, /customer-orders-workspace/);
  assert.match(ordersPanel, /customer-orders-list-pane/);
  assert.match(ordersPanel, /customer-order-detail-pane/);
  assert.match(ordersPanel, /customerMonthGroups/);
  assert.match(ordersPanel, /customer-order-summary/);
  assert.match(ordersPanel, />Order summary</);
  assert.match(ordersPanel, />Products</);
  assert.match(ordersPanel, />Quantity</);
  assert.doesNotMatch(ordersPanel, /Related file/);
  assert.match(ordersPanel, /Order again/);
  assert.match(ordersPanel, /customerSelected\.items\.map/);
  assert.doesNotMatch(ordersPanel, /showAllItems|View all|Show fewer/);
  assert.doesNotMatch(ordersPanel, /order-dialog/);
});

test("customer orders stay in one desktop viewport with paged orders and internally scrolling products", () => {
  assert.match(ordersPanel, /CUSTOMER_ORDER_PAGE_SIZES = \[4, 8, 12\]/);
  assert.match(ordersPanel, /DEFAULT_CUSTOMER_ORDER_PAGE_SIZE = 8/);
  assert.match(ordersPanel, /customerPageOrders/);
  assert.match(ordersPanel, /customer-orders-pagination/);
  assert.match(ordersPanel, />Per page <select/);
  assert.match(ordersPanel, /aria-label="Next order page"/);
  assert.match(styles, /\.customer-orders-page[\s\S]*height: calc\(100dvh - 76px\)[\s\S]*overflow: hidden/);
  assert.match(styles, /\.customer-order-products-table \{ min-height: 0; overflow: auto; flex: 1 1 auto/);
});

test("customer order details expose one unambiguous Excel download action", () => {
  assert.doesNotMatch(ordersPanel, />Download<\/a><\/td>/);
  assert.doesNotMatch(ordersPanel, /aria-label="Download order Excel"/);
  assert.equal((ordersPanel.match(/>Download Excel<\/a>/g) || []).length, 1);
});

test("new orders preserve immutable line items for detail and reorder", () => {
  assert.match(orderService, /interface CustomerOrderItem/);
  assert.match(orderService, /form\.set\("items_json"/);
  assert.match(quoteBuilder, /const orderItems = exportProducts\.map/);
  assert.match(quoteBuilder, /unitPriceCents: price/);
  assert.match(quoteBuilder, /imageUrl: image\?\.thumbnailUrl/);
});
