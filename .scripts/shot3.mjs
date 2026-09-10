import { chromium } from 'playwright';
import path from 'path';

const browser = await chromium.launch();
const file = 'file://' + path.resolve('index.html');

for (const [name, size] of [['mobile', {width:390, height:844}], ['tablet', {width:820, height:1100}], ['desktop', {width:1440, height:900}], ['wide', {width:1920, height:1000}]]) {
  const page = await browser.newPage({ viewport: size });
  await page.goto(file);
  await page.screenshot({ path: `/tmp/shot-${name}2.png` });
  await page.close();
}
await browser.close();
console.log('done');
