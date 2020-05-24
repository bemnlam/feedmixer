
const jsdom = require('jsdom');
const fs = require('fs');

const src = './raw-d.html';
const dest = './default_feeds/feeds.txt';
// const selector = '.compact-media-item-image';
const selector = '.yt-simple-endpoint.style-scope.ytd-grid-channel-renderer';
const appRoot = 'https://www.youtube.com/feeds/videos.xml?channel_id=';

const { JSDOM } = jsdom;

const rawHtml = fs.readFileSync(src, 'utf-8');

const dom = new JSDOM(rawHtml);
const doc = dom.window.document;
const parsed = [...doc.querySelectorAll(selector)].map((n) => n.getAttribute('href').replace('/channel/', ''));

// // eslint-disable-next-line no-console
// console.table(parsed);
const buffer = parsed.sort().map((id) => `${appRoot}${id}`).join('\n');

fs.writeFileSync(dest, buffer);
