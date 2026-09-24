import assert from "node:assert/strict";
import test from "node:test";
import {
  batchIdentityValidationError,
  buildBatchDriveName,
  syncDriveFolderWithEnglishName,
  syncDriveNameWithEnglishName,
} from "../src/admin/batchIdentity.ts";

test("a single asset keeps the exact edited filename", () => {
  assert.equal(
    buildBatchDriveName("6016689 Bear Plush Fairway Wood Cover.jpg", { name: "画板 15.jpg", driveName: "" }, 0, 1),
    "6016689 Bear Plush Fairway Wood Cover.jpg",
  );
});

test("a batch keeps each source number and extension", () => {
  const template = "6016270 Black Rhombus Iron Headcover Set 10PCS.jpg";
  assert.equal(
    buildBatchDriveName(template, { name: "1464x600(2).jpg", driveName: template }, 0, 2),
    "6016270 Black Rhombus Iron Headcover Set 10PCS (2).jpg",
  );
  assert.equal(
    buildBatchDriveName(template, { name: "1464x600(3).png", driveName: template }, 1, 2),
    "6016270 Black Rhombus Iron Headcover Set 10PCS (3).png",
  );
});

test("a batch adds stable numbers when source filenames have none", () => {
  const template = "6016689 Bear Plush Fairway Wood Cover.jpg";
  assert.equal(
    buildBatchDriveName(template, { name: "front.jpg", driveName: "" }, 0, 2),
    "6016689 Bear Plush Fairway Wood Cover (1).jpg",
  );
  assert.equal(
    buildBatchDriveName(template, { name: "back.png", driveName: "" }, 1, 2),
    "6016689 Bear Plush Fairway Wood Cover (2).png",
  );
});

test("product descriptors in parentheses are not removed", () => {
  const template = "6016270 Iron Headcover Set 10PCS (4-9, P, A, S, L).jpg";
  assert.equal(
    buildBatchDriveName(template, { name: "detail(2).jpg", driveName: "" }, 1, 2),
    "6016270 Iron Headcover Set 10PCS (4-9, P, A, S, L) (2).jpg",
  );
});

test("identity validation explains a numeric-only English name", () => {
  assert.equal(
    batchIdentityValidationError({ sku: "7016689", englishName: "42143", driveName: "DSC00478.JPG" }),
    "英文品名必须包含英文字母，不能只填写数字。",
  );
});

test("identity validation explains a Chinese filename", () => {
  assert.equal(
    batchIdentityValidationError({ sku: "7016689", englishName: "Golf Headcover", driveName: "产品主图.JPG" }),
    "文件名只能使用英文字符，不能包含中文或特殊字符。",
  );
});

test("identity validation accepts valid batch identity fields", () => {
  assert.equal(
    batchIdentityValidationError({ sku: "7016689", englishName: "Golf Headcover", driveName: "7016689 Golf Headcover.JPG" }),
    "",
  );
});

test("editing an overlapping English name synchronizes the filename and product folder exactly", () => {
  const sku = "7203100";
  const englishName = "Child Safety Booster Seat for Golf Cart";
  assert.equal(
    syncDriveNameWithEnglishName(
      "7203100 Child Safety Booster Seat for Golf Carts (1).jpg",
      sku,
      englishName,
      englishName,
    ),
    "7203100 Child Safety Booster Seat for Golf Cart (1).jpg",
  );
  assert.equal(
    syncDriveFolderWithEnglishName(
      "04 Product Images/01 Craftsman Golf/Golf Accessories/7203100 Child Safety Booster Seat for Golf Carts",
      sku,
      englishName,
      englishName,
    ),
    "04 Product Images/01 Craftsman Golf/Golf Accessories/7203100 Child Safety Booster Seat for Golf Cart",
  );
});
