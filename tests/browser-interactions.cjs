// Real browser contract tests; run explicitly with node --test.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const script = path.resolve(__dirname, "../full_harness/browser/check.cjs");
test("hover without click, geometry, write observation, and touch context", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "browser-contract-"));
  fs.writeFileSync(
    path.join(dir, "index.html"),
    `<!doctype html><style>.tip{display:none;position:absolute;top:50px}@media(hover:hover){button:hover .tip{display:block}}</style><button onclick="localStorage.setItem('clicked','yes');document.querySelector('p').textContent='Tapped'">Filter<span class="tip" aria-hidden="true">Explanation</span></button><p>Waiting</p>`,
  );
  const run = (steps, name) => {
    const output = path.join(dir, name);
    fs.mkdirSync(output);
    const plan = path.join(dir, name + ".json");
    fs.writeFileSync(plan, JSON.stringify(steps));
    const proc = spawnSync(process.execPath, [script, dir, output, plan], {
      encoding: "utf8",
    });
    const result = JSON.parse(
      fs.readFileSync(path.join(output, "browser.json")),
    );
    return { proc, result };
  };
  try {
    const desktop = run(
      [
        { action: "snapshot_geometry", selector: "button" },
        { action: "snapshot_storage" },
        { action: "hover", role: "button", name: "Filter", duration_ms: 100 },
        { action: "visible", text: "Explanation" },
        { action: "visible", text: "Waiting" },
        { action: "unchanged_geometry", selector: "button" },
        { action: "unchanged_storage" },
        { action: "unchanged_storage_writes" },
        { action: "pointer", x: 500, y: 500 },
        { action: "absent", text: "Explanation" },
      ],
      "desktop",
    );
    assert.equal(desktop.proc.status, 0, desktop.proc.stderr);
    const touch = run(
      [
        { action: "device", touch: true, width: 390 },
        { action: "tap", role: "button", name: "Filter" },
        { action: "visible", text: "Tapped" },
        { action: "absent", text: "Explanation" },
      ],
      "touch",
    );
    assert.equal(touch.proc.status, 0, touch.proc.stderr);
    assert.equal(touch.result.device.hasTouch, true);
    const bad = run(
      [
        { action: "snapshot_storage" },
        { action: "click", role: "button", name: "Filter" },
        { action: "unchanged_storage_writes" },
      ],
      "writes",
    );
    assert.notEqual(bad.proc.status, 0);
    assert.match(bad.result.failure, /storage.*write/i);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
