// Trusted Runner program. Plans contain data, never host JavaScript or commands.
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

async function main() {
  const probe = process.argv[2] === "--probe";
  const root = probe ? null : fs.realpathSync(process.argv[2]);
  const output = probe ? null : process.argv[3];
  const plan = probe
    ? []
    : JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
  if (!Array.isArray(plan) || plan.length > 80)
    throw new Error("Expected at most 80 browser steps");
  const types = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
  };
  const server = http.createServer((req, res) => {
    if (probe)
      return res.end("<html><body>browser capability probe</body></html>");
    try {
      const pathname = decodeURIComponent(
        new URL(req.url, "http://localhost").pathname,
      );
      if (pathname.split("/").some((p) => p.startsWith(".")))
        throw new Error("hidden path");
      const file = fs.realpathSync(
        path.join(root, pathname === "/" ? "index.html" : pathname),
      );
      if (
        !file.startsWith(root + path.sep) ||
        !fs.statSync(file).isFile() ||
        !types[path.extname(file)]
      )
        throw new Error("path");
      res.setHeader("Content-Type", types[path.extname(file)]);
      res.end(fs.readFileSync(file));
    } catch {
      res.writeHead(404);
      res.end("Not found");
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  let browser;
  try {
    browser = await chromium.launch({ headless: true, chromiumSandbox: true });
    const deviceStep = plan[0]?.action === "device" ? plan[0] : null;
    if (
      deviceStep &&
      (typeof deviceStep.touch !== "boolean" ||
        !Number.isInteger(deviceStep.width) ||
        deviceStep.width < 320 ||
        deviceStep.width > 1920)
    )
      throw new Error("device requires touch boolean and width 320..1920");
    const device = {
      hasTouch: deviceStep?.touch ?? false,
      isMobile: deviceStep?.touch ?? false,
      viewport: {
        width: deviceStep?.width ?? 1440,
        height: deviceStep ? 844 : 1000,
      },
    };
    const context = await browser.newContext({
      ...device,
      serviceWorkers: "block",
      acceptDownloads: true,
    });
    const base = `http://127.0.0.1:${server.address().port}`;
    await context.route("**/*", (route) =>
      route
        .request()
        .url()
        .startsWith(base + "/")
        ? route.continue()
        : route.abort(),
    );
    await context.routeWebSocket("**/*", (socket) => socket.close());
    let storageWrites = 0;
    await context.exposeBinding("__harnessStorageWrite", () => {
      storageWrites++;
    });
    await context.addInitScript(() => {
      window.__harnessPendingWrites = [];
      for (const name of ["setItem", "removeItem", "clear"]) {
        const original = Storage.prototype[name];
        Storage.prototype[name] = function (...args) {
          if (this === window.localStorage)
            window.__harnessPendingWrites.push(window.__harnessStorageWrite());
          return Reflect.apply(original, this, args);
        };
      }
    });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    const errors = [],
      performed = [],
      downloads = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const response = await page.goto(base + "/");
    if (!response.ok() || !(await page.locator("body").innerText()).trim())
      throw new Error("Page failed to load");
    if (probe) {
      console.log(
        "Browser dependency, localhost, launch and page rendering passed",
      );
      return;
    }
    let failure = null,
      storage,
      writeSnapshot;
    const geometry = new Map();
    try {
      for (const step of plan) {
        const locator = step.selector
          ? page.locator(step.selector)
          : step.label
            ? page.getByLabel(step.label, { exact: true })
            : step.role
              ? page.getByRole(step.role, { name: step.name, exact: true })
              : step.text
                ? page.getByText(step.text, { exact: true })
                : null;
        switch (step.action) {
          case "device":
            if (step !== plan[0])
              throw new Error("device must be the first step");
            break;
          case "hover":
            await locator.hover();
            if (step.duration_ms !== undefined) {
              if (
                !Number.isInteger(step.duration_ms) ||
                step.duration_ms < 0 ||
                step.duration_ms > 2000
              )
                throw new Error("Invalid hover duration_ms");
              await page.waitForTimeout(step.duration_ms);
            }
            break;
          case "pointer": {
            const size = page.viewportSize();
            if (
              ![step.x, step.y].every(Number.isFinite) ||
              step.x < 0 ||
              step.y < 0 ||
              step.x >= size.width ||
              step.y >= size.height
            )
              throw new Error("Pointer outside viewport");
            await page.mouse.move(step.x, step.y);
            break;
          }
          case "tap":
            await locator.tap();
            break;
          case "snapshot_geometry":
          case "unchanged_geometry": {
            const key = JSON.stringify([
              step.selector,
              step.label,
              step.role,
              step.name,
              step.text,
            ]);
            const boxes = await locator.evaluateAll((elements) =>
              elements.map((el) => {
                const r = el.getBoundingClientRect();
                return { x: r.x, y: r.y, width: r.width, height: r.height };
              }),
            );
            if (!boxes.length) throw new Error("No geometry targets matched");
            if (step.action === "snapshot_geometry") geometry.set(key, boxes);
            else {
              const before = geometry.get(key);
              if (!before)
                throw new Error(
                  "snapshot_geometry must run first for this locator",
                );
              assert.equal(
                boxes.length,
                before.length,
                "Geometry target count changed",
              );
              boxes.forEach((box, i) =>
                Object.keys(box).forEach((k) =>
                  assert.ok(
                    Math.abs(box[k] - before[i][k]) <= 0.5,
                    "Geometry changed: " + k,
                  ),
                ),
              );
            }
            break;
          }
          case "unchanged_storage_writes":
            if (writeSnapshot === undefined)
              throw new Error("snapshot_storage must run first");
            await page.evaluate(() =>
              Promise.all(window.__harnessPendingWrites),
            );
            assert.equal(
              storageWrites,
              writeSnapshot,
              "localStorage write attempts changed",
            );
            break;
          case "fill":
            await locator.fill(step.value);
            break;
          case "click":
            await locator.click();
            break;
          case "visible":
            await locator.waitFor({ state: "visible" });
            break;
          case "absent":
            await locator.waitFor({ state: "hidden" });
            break;
          case "reload":
            await page.reload();
            break;
          case "viewport":
            if (
              !Number.isInteger(step.width) ||
              step.width < 320 ||
              step.width > 1920
            )
              throw new Error("Invalid viewport width");
            await page.setViewportSize({ width: step.width, height: 844 });
            break;
          case "key":
            if (
              ![
                "Tab",
                "Enter",
                "Escape",
                "Space",
                "ArrowDown",
                "ArrowUp",
              ].includes(step.key)
            )
              throw new Error("Unsupported key");
            await page.keyboard.press(step.key === "Space" ? " " : step.key);
            break;
          case "snapshot_storage":
            await page.evaluate(() =>
              Promise.all(window.__harnessPendingWrites),
            );
            writeSnapshot = storageWrites;
            storage = await page.evaluate(() =>
              JSON.stringify(Object.entries(localStorage).sort()),
            );
            break;
          case "unchanged_storage":
            if (storage === undefined)
              throw new Error("snapshot_storage must run first");
            assert.equal(
              await page.evaluate(() =>
                JSON.stringify(Object.entries(localStorage).sort()),
              ),
              storage,
            );
            break;
          case "storage_write_failure":
            if (typeof step.enabled !== "boolean")
              throw new Error("storage_write_failure requires boolean enabled");
            await page.evaluate((enabled) => {
              // A page-scoped fault: reload discards it, disabling restores writes.
              if (!window.__harnessStorageFault) {
                const original = Storage.prototype.setItem;
                const fault = { enabled: false };
                Storage.prototype.setItem = function (...args) {
                  if (fault.enabled && this === window.localStorage)
                    throw new DOMException(
                      "Injected localStorage write failure",
                      "QuotaExceededError",
                    );
                  return Reflect.apply(original, this, args);
                };
                window.__harnessStorageFault = fault;
              }
              window.__harnessStorageFault.enabled = enabled;
            }, step.enabled);
            break;
          case "fail_download":
            await page.evaluate(() => {
              URL.createObjectURL = () => {
                throw new Error("Injected download failure");
              };
            });
            break;
          case "download": {
            const ready = page.waitForEvent("download");
            await locator.click();
            const download = await ready;
            if (await download.failure())
              throw new Error(await download.failure());
            const name = download.suggestedFilename();
            if (step.filename && name !== step.filename)
              throw new Error("Downloaded filename differs");
            if (step.suffix && !name.endsWith(step.suffix))
              throw new Error("Downloaded filename suffix differs");
            const saved = path.join(
              output,
              `download-${downloads.length + 1}.json`,
            );
            await download.saveAs(saved);
            const contents = JSON.parse(
              new TextDecoder("utf-8", { fatal: true }).decode(
                fs.readFileSync(saved),
              ),
            );
            if ("expected" in step) assert.deepEqual(contents, step.expected);
            downloads.push({
              filename: name,
              file: path.basename(saved),
              contents,
            });
            break;
          }
          default:
            throw new Error("Unsupported action: " + step.action);
        }
        performed.push(step);
      }
      if (errors.length) throw new Error(errors.join("\n"));
    } catch (error) {
      failure = error.message;
    }
    await page.screenshot({
      path: path.join(output, "screenshot.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(output, "mobile.png"),
      fullPage: true,
    });
    fs.writeFileSync(
      path.join(output, "browser.json"),
      JSON.stringify(
        {
          passed: !failure,
          performed,
          errors,
          failure,
          downloads,
          device,
          storageWrites,
        },
        null,
        2,
      ),
    );
    if (failure) throw new Error(failure);
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}
main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
