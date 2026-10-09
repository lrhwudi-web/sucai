import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

let compiled = ts.transpileModule(readFileSync(new URL("../src/services/useDriveTransfers.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
compiled = compiled.replace(/^import .+;\r?\n/gm, "").replace("export function", "function");
const makeHook = new Function("useEffect", "useRef", "useState", "getProductDriveCopyStatus", "prepareProductDriveCopy", "SessionExpiredError", "window", `${compiled}; return useDriveTransfers;`);

function harness(prepare, status) {
  let visible = []; const cleanups = [];
  const hook = makeHook((effect) => cleanups.push(effect()), (value) => ({ current: value }), () => [visible, (next) => visible = next], status, prepare, class extends Error {}, { setTimeout: (callback) => { queueMicrotask(callback); return 1; }, open: () => { throw Error("Async pop-ups must not be used"); } });
  const manager = hook(7, () => {});
  return { manager, snapshot: () => visible, dispose: () => cleanups.forEach((cleanup) => cleanup?.()) };
}
async function settle(h) {
  for (let i = 0; i < 500; i++) {
    if (h.snapshot().every((job) => ["ready", "error"].includes(job.state))) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  throw Error("Drive queue did not settle");
}

test("two Drive preparations retain both results, run sequentially and survive more than 120 polls", async () => {
  const started = []; let polls = 0;
  const h = harness(async (sku) => { started.push(sku); return { job_id: sku, state: "building", progress: 5 }; }, async (sku) => {
    polls++; return sku === "1" && polls <= 160 ? { job_id: sku, state: "building", progress: 79 } : { job_id: sku, state: "ready", folder_url: `https://drive.google.com/drive/folders/${sku}` };
  });
  h.manager.add("1"); h.manager.add("2"); h.manager.add("1");
  assert.deepEqual(h.snapshot().map((job) => job.sku), ["1", "2"]);
  await settle(h);
  assert.deepEqual(started, ["1", "2"]); assert.ok(polls > 120);
  assert.deepEqual(h.snapshot().map((job) => job.folderUrl), ["https://drive.google.com/drive/folders/1", "https://drive.google.com/drive/folders/2"]);
  h.dispose();
});

test("one failed Drive task does not hide another and can be retried", async () => {
  let failed = true;
  const h = harness(async (sku) => ({ job_id: sku, state: failed && sku === "1" ? "error" : "ready", error: "Quota temporarily exceeded", folder_url: `https://drive.google.com/drive/folders/${sku}` }), async () => { throw Error("Ready tasks need no polling"); });
  h.manager.add("1"); h.manager.add("2"); await settle(h);
  assert.equal(h.snapshot()[0].state, "error"); assert.equal(h.snapshot()[1].state, "ready");
  failed = false; h.manager.retry("1"); await settle(h);
  assert.ok(h.snapshot().every((job) => job.state === "ready")); h.dispose();
});

test("brief status failures are retried and logout stops queued tasks", async () => {
  let failures = 0; const started = [];
  const h = harness(async (sku) => { started.push(sku); return { job_id: sku, state: "building", progress: 5 }; }, async (sku) => {
    if (++failures <= 4) throw Error("Network unavailable"); return { job_id: sku, state: "ready", folder_url: `https://drive.google.com/drive/folders/${sku}` };
  });
  h.manager.add("1"); await settle(h); assert.equal(h.snapshot()[0].state, "ready");
  h.manager.add("2"); h.dispose(); await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(started, ["1"]);
});
