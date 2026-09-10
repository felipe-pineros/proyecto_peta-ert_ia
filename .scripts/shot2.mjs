import { chromium } from 'playwright';
import path from 'path';

const browser = await chromium.launch();
const file = 'file://' + path.resolve('index.html');

const page = await browser.newPage({ viewport: {width:390, height:2400} });
await page.goto(file);
await page.screenshot({ path: `/tmp/shot-mobile-full.png`, fullPage: true });
await page.close();
await browser.close();
console.log('done');
