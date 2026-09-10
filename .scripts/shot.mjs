import { chromium } from 'playwright';
import path from 'path';

const browser = await chromium.launch();
const file = 'file://' + path.resolve('index.html');

for (const [name, size] of [['mobile', {width:390, height:844}], ['desktop', {width:1440, height:900}]]) {
  const page = await browser.newPage({ viewport: size });
  await page.goto(file);
  await page.screenshot({ path: `/tmp/shot-${name}.png` });
  await page.close();
}
await browser.close();
console.log('done');
