// Fixed browser harness, never execute an agent-provided test script on the host.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

async function main() {
  const root = fs.realpathSync(process.argv[2]);
  const output = process.argv[3];
  const plan = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
  if (!Array.isArray(plan) || plan.length > 40) throw new Error('Invalid browser plan');
  const server = http.createServer((req, res) => {
    try {
      const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
      const file = fs.realpathSync(path.join(root, pathname === '/' ? 'index.html' : pathname));
      if (!file.startsWith(root + path.sep) || !fs.statSync(file).isFile()) throw new Error('path');
      const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml'};
      res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
      res.end(fs.readFileSync(file));
    } catch { res.writeHead(404); res.end('Not found'); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const context = await browser.newContext({viewport:{width:1440,height:1000}, serviceWorkers:'block'});
    const base = `http://127.0.0.1:${server.address().port}`;
    await context.route('**/*', route => {
      const url = route.request().url();
      return url.startsWith(base + '/') ? route.continue() : route.abort();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const response = await page.goto(base + '/');
    if (!response.ok()) throw new Error('Page failed to load');
    if (!(await page.locator('body').innerText()).trim()) throw new Error('Empty page');
    const performed = [];
    let failure = null;
    try {
      for (const step of plan) {
        const locator = step.label ? page.getByLabel(step.label, {exact:true})
          : step.role ? page.getByRole(step.role, {name:step.name, exact:true})
          : step.text ? page.getByText(step.text, {exact:true}) : null;
        switch(step.action) {
          case 'fill': await locator.fill(step.value); break;
          case 'click': await locator.click(); break;
          case 'visible': await locator.waitFor({state:'visible'}); break;
          case 'absent': await locator.waitFor({state:'hidden'}); break;
          case 'reload': await page.reload(); break;
          default: throw new Error('Unsupported test action: expected a flat array of steps, each with action fill/click/visible/absent/reload; no name/steps wrapper');
        }
        performed.push(step);
      }
      if (errors.length) throw new Error(errors.join('\n'));
    } catch (e) { failure = e.message; }
    await page.screenshot({path:path.join(output,'screenshot.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    fs.writeFileSync(path.join(output,'browser.json'), JSON.stringify({passed:!failure,performed,errors,failure},null,2));
    if (failure) throw new Error(failure);
  } finally {
    if(browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error.message); process.exitCode=1; });
