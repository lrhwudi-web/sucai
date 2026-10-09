import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../src/services/assetDownloads.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { AssetDownloadQueue, safeDownloadName, downloadIsActive } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const asset = (id, name = `${id}.jpg`, path = "") => ({ id, name, downloadUrl: `/download/${id}`, size: 3, path });
const product = (sku, assets = [asset(sku)]) => ({ sku, name: `Product ${sku}`, assets });

function memoryDirectory(name = "Downloads") {
  return {
    name, dirs: new Map(), files: new Map(),
    async getDirectoryHandle(name, { create } = {}) {
      if (!this.dirs.has(name)) {
        if (!create) throw Object.assign(new Error("Not found"), { name: "NotFoundError" });
        this.dirs.set(name, memoryDirectory(name));
      }
      return this.dirs.get(name);
    },
    async getFileHandle(name) {
      const file = this.files.get(name) || { bytes: [], closes: 0, aborts: 0, writes: 0 };
      this.files.set(name, file);
      return { async createWritable() {
        let chunks = [];
        return { async write(bytes) { chunks.push(...bytes); file.writes++; }, async close() { file.bytes = chunks; file.closes++; }, async abort() { chunks = []; file.aborts++; } };
      } };
    },
  };
}

async function settle(queue) {
  for (let index = 0; index < 200; index++) { if (!queue.snapshot().some(downloadIsActive)) return; await tick(); }
  throw new Error("Queue did not settle.");
}

const fileResponse = () => new Response(new Uint8Array([1, 2, 3]), { headers: { "content-type": "application/octet-stream" } });

test("multiple product tasks retain independent progress, deduplicate repeated clicks, and limit streams to two", async () => {
  const root = memoryDirectory(); const gates = []; const started = [];
  const queue = new AssetDownloadQueue(async (sku) => product(sku), async (url, options) => {
    assert.equal(options.credentials, "include"); assert.equal(options.redirect, "error");
    started.push(url); await new Promise((resolve) => gates.push(resolve)); return fileResponse();
  });
  queue.add([product("1"), product("2"), product("3")], root); queue.add([product("1")], root);
  for (let index = 0; index < 10 && gates.length < 2; index++) await tick();
  assert.deepEqual(started, ["/download/1", "/download/2"]);
  assert.deepEqual(queue.snapshot().map((job) => job.sku), ["1", "2", "3"]);
  assert.equal(queue.snapshot()[2].state, "queued");
  gates[0](); gates[1]();
  for (let index = 0; index < 10 && gates.length < 3; index++) await tick();
  gates[2](); await settle(queue);
  assert.ok(queue.snapshot().every((job) => job.state === "ready" && job.completed === 1));
  assert.equal(root.dirs.size, 3);
});

test("retry saves only remaining files while another product continues after a failure", async () => {
  const root = memoryDirectory(); const calls = []; let failing = true;
  const products = [product("1", [asset("a"), asset("b")]), product("2")];
  const queue = new AssetDownloadQueue(async (sku) => products.find((p) => p.sku === sku), async (url) => {
    calls.push(url); if (url === "/download/b" && failing) return new Response("Failed", { status: 503 }); return fileResponse();
  });
  queue.add(products, root); await settle(queue);
  assert.equal(queue.snapshot()[0].state, "error"); assert.equal(queue.snapshot()[0].completed, 1);
  assert.equal(queue.snapshot()[1].state, "ready");
  failing = false; queue.retry("1"); await settle(queue);
  assert.equal(calls.filter((url) => url === "/download/a").length, 1);
  assert.equal(calls.filter((url) => url === "/download/b").length, 2);
  assert.equal(queue.snapshot()[0].completed, 2); assert.equal(queue.snapshot()[0].state, "ready");
});

test("saving chunks uses a writable stream and declares saved only after closing it", async () => {
  const root = memoryDirectory(); let release;
  const queue = new AssetDownloadQueue(async (sku) => product(sku), async () => new Response(new ReadableStream({ async start(controller) {
    controller.enqueue(new Uint8Array([1])); await new Promise((resolve) => release = resolve); controller.enqueue(new Uint8Array([2, 3])); controller.close();
  } })));
  queue.add([product("1")], root); await tick(); await tick();
  assert.equal(queue.snapshot()[0].completed, 0);
  assert.equal([...root.dirs.values()][0].files.get("1.jpg").closes, 0);
  release(); await settle(queue);
  const file = [...root.dirs.values()][0].files.get("1.jpg");
  assert.deepEqual(file.bytes, [1, 2, 3]); assert.equal(file.writes, 2); assert.equal(file.closes, 1);
});

test("an incomplete response never commits a partial file or reports success", async () => {
  const root = memoryDirectory();
  const queue = new AssetDownloadQueue(async (sku) => product(sku), async () => new Response(new Uint8Array([1])));
  queue.add([product("1")], root); await settle(queue);
  assert.equal(queue.snapshot()[0].state, "error"); assert.equal(queue.snapshot()[0].completed, 0);
  const file = [...root.dirs.values()][0].files.get("1.jpg");
  assert.equal(file.closes, 0); assert.equal(file.aborts, 1); assert.deepEqual(file.bytes, []);
});

test("a cancelled download aborts pending writes and releases the stream before retry", async () => {
  const root = memoryDirectory(); let requestStarted; const started = new Promise((resolve) => requestStarted = resolve);
  const queue = new AssetDownloadQueue(async (sku) => product(sku), async (_url, { signal }) => new Response(new ReadableStream({ start(controller) {
    controller.enqueue(new Uint8Array([1])); requestStarted(); signal.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true });
  } })));
  queue.add([product("1")], root); await started; await tick(); queue.cancel("1"); await settle(queue);
  assert.equal(queue.snapshot()[0].state, "cancelled"); assert.equal(queue.snapshot()[0].completed, 0);
  const file = [...root.dirs.values()][0].files.get("1.jpg"); assert.equal(file.closes, 0); assert.equal(file.aborts, 1);
});

test("nested folders and case-insensitive filename collisions preserve both assets", async () => {
  const root = memoryDirectory();
  const files = [asset("a", "Same.jpg", "Drive/1 Product/Details/Same.jpg"), asset("b", "same.jpg", "Drive/1 Product/Details/same.jpg")];
  const queue = new AssetDownloadQueue(async (sku) => product(sku, files), async () => fileResponse());
  queue.add([product("1")], root); await settle(queue);
  const details = [...root.dirs.values()][0].dirs.get("Details");
  assert.deepEqual([...details.files.keys()], ["Same.jpg", "same (1).jpg"]);
  assert.equal(queue.snapshot()[0].completed, 2);
});

test("existing product folders are preserved and a new destination downloads the entire product", async () => {
  const root = memoryDirectory(); await root.getDirectoryHandle("1 Product 1", { create: true });
  let fail = true; const calls = [];
  const queue = new AssetDownloadQueue(async (sku) => product(sku, [asset("a"), asset("b")]), async (url) => {
    calls.push(url); return fail && url === "/download/b" ? new Response(null, { status: 503 }) : fileResponse();
  });
  queue.add([product("1")], root); await settle(queue);
  assert.ok(root.dirs.has("1 Product 1 (1)"));
  const other = memoryDirectory("Other"); fail = false; queue.retry("1", other); await settle(queue);
  assert.equal(calls.filter((url) => url === "/download/a").length, 2);
  assert.equal([...other.dirs.values()][0].files.size, 2);
});

test("unauthenticated and HTML responses do not become files", async () => {
  for (const response of [new Response(null, { status: 401 }), new Response("login", { headers: { "content-type": "text/html" } })]) {
    const root = memoryDirectory(); const queue = new AssetDownloadQueue(async (sku) => product(sku), async () => response);
    queue.add([product("1")], root); await settle(queue);
    assert.equal(queue.snapshot()[0].state, "error"); assert.equal([...root.dirs.values()][0].files.size, 0);
  }
});

test("unsupported browsers expose authenticated individual links without claiming files were saved", async () => {
  const queue = new AssetDownloadQueue(async (sku) => product(sku), async () => { throw Error("Must not auto-download"); });
  queue.add([product("1"), product("2")], null); await settle(queue);
  assert.ok(queue.snapshot().every((job) => job.state === "manual" && job.completed === 0 && job.assets.length === 1));
});

test("individual file links can switch to folder saving after a destination is selected", async () => {
  const root = memoryDirectory();
  const calls = [];
  const queue = new AssetDownloadQueue(async (sku) => product(sku), async (url) => { calls.push(url); return fileResponse(); });
  queue.add([product("1"), product("2")], null); await settle(queue);
  assert.equal(calls.length, 0);
  queue.retry("1", root); await settle(queue);
  assert.equal(queue.snapshot()[0].state, "ready");
  assert.equal(queue.snapshot()[0].completed, 1);
  assert.equal(queue.snapshot()[1].state, "manual");
  assert.deepEqual(calls, ["/download/1"]);
});

test("Windows reserved names, traversal and invalid characters are neutralized", () => {
  assert.equal(safeDownloadName("CON.jpg"), "_CON.jpg"); assert.equal(safeDownloadName("../../bad:file?.jpg"), ".._.._bad_file_.jpg");
  assert.equal(safeDownloadName(".."), "asset"); assert.equal(safeDownloadName("hello.jpg. "), "hello.jpg");
  assert.ok(safeDownloadName("x".repeat(300) + ".mp4").endsWith(".mp4"));
});
