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
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
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
      storage;
    try {
      for (const step of plan) {
        const locator = step.label
          ? page.getByLabel(step.label, { exact: true })
          : step.role
            ? page.getByRole(step.role, { name: step.name, exact: true })
            : step.text
              ? page.getByText(step.text, { exact: true })
              : null;
        switch (step.action) {
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
              !["Tab", "Enter", "Space", "ArrowDown", "ArrowUp"].includes(
                step.key,
              )
            )
              throw new Error("Unsupported key");
            await page.keyboard.press(step.key === "Space" ? " " : step.key);
            break;
          case "snapshot_storage":
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
        { passed: !failure, performed, errors, failure, downloads },
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
