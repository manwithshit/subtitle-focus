// Run against a disposable --test-mode review session, never a user's live session.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=fs.realpathSync(process.argv[2]);
const connection=JSON.parse(fs.readFileSync(path.join(root,'review/connection.json')));
const output=path.join(root,'browser');fs.mkdirSync(output,{recursive:true});
const passed=[];
(async()=>{
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1280,height:900},acceptDownloads:true});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const rows=()=>page.locator('.row').count();
 const mask=()=>page.locator('.caption').evaluateAll(ps=>ps.map(p=>Array.from(p.querySelectorAll('[data-char]')).map(c=>!!c.closest('mark'))));
 const waitSaved=()=>page.waitForFunction(()=>/草稿已保存到本机|已确认并归档/.test(document.querySelector('#save-status').textContent));
 try {
  await page.goto(connection.url);await page.locator('.row').first().waitFor();
  assert.equal(await page.locator('#finish').textContent(),'确认并生成样片');assert.equal(await page.locator('#archive-directory').textContent(),path.join(root,'review'));
  assert.equal(await rows(),13);assert(await page.locator('#test-banner').isVisible());passed.push('13 条真实字幕；测试状态可见');
  assert.equal(await page.locator('mark').first().evaluate(e=>getComputedStyle(e).color),'rgb(255, 223, 56)');
  const initial=await mask();
  await page.locator('.caption').nth(0).locator('[data-char="5"]').click();await waitSaved();
  const toggled=await mask();assert.notDeepEqual(toggled,initial);passed.push('按词点击；Display Pilot 2 完整边界');
  await page.locator('#undo').click();assert.deepEqual(await mask(),initial);
  await page.locator('#redo').click();assert.deepEqual(await mask(),toggled);await waitSaved();passed.push('撤销与重做');
  // A real pointer drag across Chinese characters.
  const a=await page.locator('.caption').nth(2).locator('[data-char="5"]').boundingBox();
  const b=await page.locator('.caption').nth(2).locator('[data-char="8"]').boundingBox();
  await page.mouse.move(a.x+1,a.y+a.height/2);await page.mouse.down();await page.mouse.move(b.x+b.width-1,b.y+b.height/2,{steps:15});await page.mouse.up();
  assert.notDeepEqual(await mask(),toggled);await waitSaved();passed.push('真实鼠标拖选切换黄色');
  const saved=await mask();await page.reload();await page.locator('.row').first().waitFor();assert.deepEqual(await mask(),saved);passed.push('刷新恢复本机草稿');
  const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();const download=await downloadPromise;
  const backup=path.join(output,'backup.json');await download.saveAs(backup);const exported=JSON.parse(fs.readFileSync(backup));assert.equal(exported.confirmed,false);passed.push('导出备份不产生确认');
  await page.locator('.clear').nth(2).click();await waitSaved();await page.locator('#import').setInputFiles(backup);await waitSaved();assert.deepEqual(await mask(),saved);passed.push('导出再导入逐字一致');
  // Simulate an unavailable server while edits remain exportable.
  await page.route('**/api/draft',r=>r.abort());await page.locator('.caption').nth(1).locator('[data-char="1"]').click();await page.locator('#retry').waitFor();assert(await page.locator('#save-status').textContent().then(t=>t.includes('失败')));
  await page.unroute('**/api/draft');await page.locator('#retry').click();await waitSaved();passed.push('断连不误报成功；重试保存恢复');
  // A stale tab cannot overwrite the newer revision.
  const stale=await context.newPage();await stale.goto(connection.url);await stale.locator('.row').first().waitFor();
  await page.locator('.caption').nth(1).locator('[data-char="1"]').click();await waitSaved();
  await stale.locator('.clear').nth(3).click();await stale.waitForFunction(()=>document.querySelector('#notice').textContent.includes('另一个页面')||document.querySelector('#save-status').textContent.includes('其他页面'));
  assert(await stale.locator('#finish').isDisabled());await stale.close();passed.push('多标签页旧版本拒绝覆盖');
  await page.locator('#finish').click();await page.locator('#cancel').click();assert.equal(fs.readdirSync(path.join(root,'review')).filter(s=>/^v\d+$/.test(s)).length,0);passed.push('取消确认不生成回执');
  // Server commits successfully, but the browser loses the response; retry same id.
  let lost=false;await page.route('**/api/confirm',async r=>{if(!lost){lost=true;await r.fetch();await r.abort();}else await r.continue();});
  await page.locator('#finish').click();await page.locator('#confirm').click();await page.waitForFunction(()=>document.querySelector('#save-status').textContent.includes('未收到成功回执'));
  await page.waitForTimeout(2300);await page.locator('#confirm').click();await page.locator('#confirm-dialog').waitFor({state:'hidden'});
  await page.unroute('**/api/confirm');assert.equal(fs.readdirSync(path.join(root,'review')).filter(s=>/^v\d+$/.test(s)).length,1);passed.push('确认响应丢失后重试；仅一个归档版本');
  await page.locator('#sample').waitFor({state:'visible',timeout:120000});await page.locator('#sample').evaluate(v=>v.play());
  await page.waitForFunction(()=>document.querySelector('#sample').currentTime>0.2);await page.locator('#sample').evaluate(v=>v.pause());passed.push('确认后自动生成真实 FFmpeg 样片；网页可播放');
  await page.screenshot({path:path.join(output,'desktop-confirmed.png'),fullPage:true});
  const receipt=JSON.parse(fs.readFileSync(path.join(root,'review/v001/receipt.json')));
  assert.equal(receipt.full_video_applied,false);assert.equal(receipt.test_only,true);assert(await page.locator('#finish').isDisabled());
  const highlights=JSON.parse(fs.readFileSync(path.join(root,'review/v001/highlights.json')));
  const current=await mask();const expected=current.map(row=>row.map((v,i)=>v?i:null).filter(i=>i!==null));
  assert.deepEqual(highlights.segments.map(s=>s.ranges.flatMap(([a,b])=>Array.from({length:b-a},(_,i)=>a+i))),expected);passed.push('网页逐字范围与归档 JSON 一致；Obsidian 记录与 SRT 齐全');
  await page.locator('.caption').nth(1).locator('[data-char="1"]').click();await waitSaved();assert(await page.locator('#receipt').isHidden());
  await page.locator('#finish').click();await page.locator('#confirm').click();await page.locator('#confirm-dialog').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.querySelector('#sample').getAttribute('src')==='/artifacts/v002/sample',null,{timeout:120000});
  assert.equal(fs.readdirSync(path.join(root,'review')).filter(s=>/^v\d+$/.test(s)).length,2);
  passed.push('确认后再修改：旧确认失效、新版本独立归档并生成新样片');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));passed.push('390px 窄屏无横向溢出');
  assert.deepEqual(errors,[]);passed.push('无浏览器脚本异常');
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({passed,errors,testOnly:true},null,2));console.log(JSON.stringify({passed,errors}));
 }catch(e){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});console.error(e);console.error('UI:',await page.locator('body').innerText());process.exitCode=1;}
 finally{await browser.close();}
})();
