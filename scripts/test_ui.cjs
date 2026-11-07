/* Browser checks. Install Playwright separately or use the bundled runtime via NODE_PATH.
 * UI_BASE_URL selects a running app. UI_CHROMIUM_PATH selects an existing browser.
 * Set UI_LIVE_MODEL=1 for the optional two-message real-provider check (billable).
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.UI_CHROMIUM_PATH ? {executablePath:process.env.UI_CHROMIUM_PATH} : {})});
  const base = process.env.UI_BASE_URL || 'http://127.0.0.1:8001';
  const context = await browser.newContext({ viewport: {width:1440,height:1000} });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = [];
  let failNext = false;
  let pendingNext = false;
  await page.route('**/chat', async route => {
    const request = route.request().postDataJSON();
    requests.push(request);
    if (failNext) {
      failNext = false;
      return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'unavailable'})});
    }
    const outcome = pendingNext ? 'escalation_pending' : request.message.includes('human') ? 'escalated' : 'answered';
    pendingNext = false;
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      conversation_id:request.conversation_id, answer:'**A safe reply.** <img src=x onerror="window.injected=true">',
      outcome, ticket_id:outcome.startsWith('escalat')?'demo-ticket-123':null,
      sources:[{title:'Getting Started',url:'https://docs.ampere.sh/docs/getting-started'},
        {title:'Unsafe link',url:'javascript:alert(1)'}]})});
  });
  try {
    await page.goto(base);
    await page.getByText('Ready to help', {exact:true}).waitFor();
    fs.mkdirSync('.tmp', {recursive:true});
    await page.screenshot({path:'.tmp/ui-desktop.png',fullPage:true});
    assert.equal(await page.locator('#send').isDisabled(),true);
    await page.locator('[data-prompt="How do I add an agent?"]').click();
    await page.locator('.message-row.assistant').waitFor();
    assert.equal(await page.locator('.message-row.user').count(),1);
    assert.equal(await page.locator('.sources a').count(),1);
    assert.equal(await page.locator('.message-text img').count(),0);
    assert.equal(await page.locator('.message-text strong').textContent(),'A safe reply.');
    assert.equal((await page.locator('.message-row.assistant .message-text').textContent()).includes('**'),false);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    const originalConversation = requests[0].conversation_id;
    await page.locator('[data-email="rahul@example.com"]').click();
    assert.equal(await page.locator('#message').inputValue(),'rahul@example.com');
    await page.locator('#message').press('Enter');
    await page.waitForFunction(()=>document.querySelectorAll('.message-row.assistant').length===2);
    assert.equal(requests[1].conversation_id,originalConversation);
    assert.notEqual(requests[0].request_id,requests[1].request_id);
    await page.reload();
    assert.equal(await page.locator('.message-row').count(),4);
    await page.locator('#new-chat').click();
    assert.equal(await page.locator('#messages').textContent(),'');
    failNext = true;
    await page.locator('#message').fill('Test a failed request');
    await page.locator('#send').click();
    await page.locator('#error-notice').waitFor({state:'visible'});
    assert.equal(await page.locator('#message').isDisabled(),true);
    const failed = requests.at(-1);
    await page.reload();
    await page.locator('#error-notice').waitFor({state:'visible'});
    await page.locator('#retry').click();
    await page.locator('.message-row.assistant').waitFor();
    assert.deepEqual(requests.at(-1),failed);
    assert.notEqual(failed.conversation_id,originalConversation);
    assert.equal(await page.locator('.message-row.user').count(),1);
    pendingNext = true;
    await page.locator('#message').fill('I need a human');
    await page.locator('#send').click();
    await page.locator('.ticket.pending').waitFor();
    assert.match(await page.locator('.ticket.pending').textContent(),/delivery pending/);
    await page.locator('#message').fill('line one');
    const before = requests.length;
    await page.locator('#message').press('Shift+Enter');
    assert.equal(requests.length,before);
    assert.match(await page.locator('#message').inputValue(),/\n/);
    await page.screenshot({path:'.tmp/ui-conversation.png',fullPage:true});
    console.log('PASS: examples, account input, context IDs, safe sources/text, reload, error retry, pending tickets, keyboard.');
    await page.setViewportSize({width:390,height:844});
    await page.locator('#new-chat').click();
    await page.screenshot({path:'.tmp/ui-mobile.png',fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.equal(await page.locator('#send').isVisible(),true);
    console.log('PASS: mobile layout and input visibility.');
    assert.deepEqual(errors,[]);
    if (process.env.UI_LIVE_MODEL === '1') {
      const live = await context.newPage();
      await live.goto(base);
      await live.locator('#message').fill('hello');
      await live.locator('#send').click();
      await live.locator('.message-row.assistant').waitFor({timeout:75000});
      assert.ok((await live.locator('.message-row.assistant .message-text').textContent()).length < 450);
      await live.locator('#message').fill('My agent is broken.');
      await live.locator('#send').click();
      await live.waitForFunction(()=>document.querySelectorAll('.message-row.assistant').length===2,{},{timeout:75000});
      assert.match(await live.locator('.message-row.assistant .message-text').last().textContent(),/email/i);
      await live.locator('[data-email="rahul@example.com"]').click();
      await live.locator('#send').click();
      await live.waitForFunction(()=>document.querySelectorAll('.message-row.assistant').length===3,{},{timeout:75000});
      assert.match(await live.locator('.message-row.assistant .message-text').last().textContent(),/API key is missing/);
      await live.screenshot({path:'.tmp/ui-live-conversation.png',fullPage:true});
      console.log('PASS: real-provider browser greeting, account follow-up, and Rahul diagnosis.');
    }
  } finally {
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
