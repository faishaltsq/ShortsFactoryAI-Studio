import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage();
await p.goto('http://127.0.0.1:3018/');
await p.getByLabel('Tampilan studio').selectOption('medium');
await p.waitForTimeout(3500);
const rows = await p.evaluate(() => Array.from(document.querySelectorAll('[data-zone-link]')).map(n => ({zone:n.getAttribute('data-zone'), tag:n.tagName, href:n.getAttribute('href'), dis:n.getAttribute('data-zone-link-disabled')})));
console.log(JSON.stringify(rows));
await b.close();
