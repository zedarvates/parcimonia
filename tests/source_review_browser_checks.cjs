// Isolated browser checks; annotations created here are authored test fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(path.join(process.argv[4], 'playwright'));

(async () => {
  const output = path.resolve(process.argv[3]);
  fs.mkdirSync(output, {recursive: false});
  const browser = await chromium.launch({headless: true});
  const errors = [];
  try {
    const page = await browser.newPage({viewport: {width: 1366, height: 900}});
    page.on('pageerror', error => errors.push(error.message));
    const requests = [];
    page.on('request', request => requests.push(request.url()));
    await page.goto(pathToFileURL(path.resolve(process.argv[2])).href);
    await page.locator('#progress').waitFor();
    const count = await page.evaluate(() => cases.length);
    assert.ok(count > 0);
    assert.equal(await page.locator('#progress').innerText(), `0 / ${count}`);
    const blank = await page.evaluate(() => exportRecord());
    assert.ok(Object.values(blank.annotations).every(a => !a.complete && a.labels.must_retain === null && a.labels.attention === null));
    for (const [name, width, height] of [['desktop',1366,900], ['mobile',390,844]]) {
      await page.setViewportSize({width, height});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name} horizontal overflow`);
      assert.ok(await page.locator('#sourceText').isVisible());
      await page.screenshot({path: path.join(output, `${name}.png`), fullPage: true});
    }
    await page.setViewportSize({width: 1366, height: 900});
    await page.locator('#reviewer').fill('browser-fixture-reviewer');
    await page.locator('#attention').selectOption('process');
    await page.locator('#mustRetain').selectOption('unknown');
    await page.locator('#language').selectOption('en');
    await page.locator('#rationale').fill('Authored browser contract test, not independent human evidence.');
    await page.locator('#rationale').blur();
    await page.locator('#sourceReviewed').check();
    for (const select of await page.locator('select[data-candidate]').all()) {
      await select.selectOption('uncertain');
    }
    await page.locator('#complete').check();
    assert.equal(await page.locator('#progress').innerText(), `1 / ${count}`);
    const exported = await page.evaluate(() => exportRecord());
    const firstId = await page.evaluate(() => cases[index].case_id);
    assert.equal(exported.annotations[firstId].labels.must_retain, null);
    assert.equal(exported.annotations[firstId].reviewer_id, 'browser-fixture-reviewer');
    // Import then export must preserve the author, even without an active annotator.
    await page.evaluate(data => {owner=''; $('reviewer').value=''; importReview(data); draw();}, exported);
    const imported = await page.evaluate(() => exportRecord());
    assert.deepEqual(imported, exported);
    assert.equal(await page.evaluate(() => {try {importReview({...blank,packet_id:'foreign'});return false;}catch {return true;}}), true);
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#exportButton').click();
    const download = await downloadPromise;
    const exportedPath = path.join(output, 'fixture-browser-export.json');
    await download.saveAs(exportedPath);
    assert.deepEqual(JSON.parse(fs.readFileSync(exportedPath,'utf8')), exported);
    await page.reload();
    assert.equal(await page.locator('#progress').innerText(), `1 / ${count}`);
    assert.ok(requests.every(url => url.startsWith('file:')), 'unexpected network request');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify({
      origin:'authored_browser_fixture', cases:count, desktop:true, mobile:true,
      overflow:false, export_import_download:true, local_storage:true, external_requests:0,
      independent_labels_established:false, model_inference_executed:false, page_errors:errors
    },null,2));
    console.log(JSON.stringify({cases:count,desktop:true,mobile:true,export_import_download:true,external_requests:0}));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error.stack);process.exitCode=1;});
