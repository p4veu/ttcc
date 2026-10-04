import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

let chapterTick;
let onKeydown;
globalThis.window = {
    innerHeight: 1080,
    addEventListener(type, listener) { if (type === 'keydown') onKeydown = listener; },
    getComputedStyle() { return { display: 'block', visibility: 'visible', opacity: '1' }; }
};
globalThis.setInterval = callback => { chapterTick = callback; return 1; };
globalThis.setTimeout = () => 1;
const source = readFileSync(new URL('./ttcc_chapters.js', import.meta.url), 'utf8');
const { extractChapters, observeChapterResponse } = await import(
    'data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

const expected = [
    { time: 0, title: 'Początek' },
    { time: 65, title: 'Test' },
    { time: 128, title: 'Wynik' }
];

assert.deepEqual(extractChapters({ playerOverlays: { playerOverlayRenderer: {
    decoratedPlayerBarRenderer: { decoratedPlayerBarRenderer: { playerBar: {
        chapteredPlayerBarRenderer: { chapters: expected.map(chapter => ({
            chapterRenderer: { timeRangeStartMillis: String(chapter.time * 1000),
                title: { simpleText: chapter.title } }
        })) }
    } } }
} } }), expected);

assert.deepEqual(extractChapters({ engagementPanels: [{
    engagementPanelSectionListRenderer: { content: { macroMarkersListRenderer: {
        contents: ['0:00', '1:05', '2:08'].map((time, i) => ({
            macroMarkersListItemRenderer: {
                timeDescription: { simpleText: time },
                title: { runs: [{ text: expected[i].title }] }
            }
        }))
    } } }
}] }), expected);

assert.deepEqual(extractChapters({ playerOverlays: { playerOverlayRenderer: {
    decoratedPlayerBarRenderer: { decoratedPlayerBarRenderer: { playerBar: {
        multiMarkersPlayerBarRenderer: { markersMap: [{
            key: 'DESCRIPTION_CHAPTERS', value: { chapters: expected.map(item => ({
                startMillis: String(item.time * 1000), title: { simpleText: item.title }
            })) }
        }] }
    } } }
} } }), expected);

assert.deepEqual(extractChapters({ engagementPanels: [{
    engagementPanelSectionListRenderer: { content: { macroMarkersListRenderer: {
        contents: [{ macroMarkersListItemRenderer: {
            timeDescription: { simpleText: '1:00' }, title: { simpleText: 'Only' }
        } }]
    } } }
}] }), []);

observeChapterResponse({ videoDetails: { videoId: 'abcdefghijk' },
    playerOverlays: { playerOverlayRenderer: { decoratedPlayerBarRenderer: {
        decoratedPlayerBarRenderer: { playerBar: { chapteredPlayerBarRenderer: {
            chapters: expected.map(item => ({ chapterRenderer: {
                timeRangeStartMillis: item.time * 1000,
                title: { simpleText: item.title }
            } }))
        } } }
    } } }
});

// YouTube's incremental DOM replaces the progress bar; the chapter overlay
// must stay attached and update its label to the position being previewed.
class Node {
    constructor(tag) {
        this.tag = tag;
        this.children = [];
        this.style = {};
        this.parentNode = null;
        this.parentElement = null;
        this.className = '';
        this.textContent = '';
    }
    appendChild(node) {
        node.parentNode = this;
        node.parentElement = this;
        this.children.push(node);
    }
    remove() {
        if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(n => n !== this);
        this.parentNode = null;
    }
    querySelectorAll(selector) {
        return this.children.filter(n => selector === '.ttcc-chapter-tick' && n.className === 'ttcc-chapter-tick');
    }
    getBoundingClientRect() { return { left: 100, right: 900, top: 700, width: 800, height: 6 }; }
}
const html = new Node('html');
const body = new Node('body');
let slider = new Node('slider');
let preview = 65;
let previewClock = null;
const progress = { querySelector(selector) {
    if (selector === '[idomkey="elapsedTime"]') return previewClock;
    if (selector !== '[role="slider"][aria-valuenow]') return null;
    return { getAttribute(name) {
        return ({ 'aria-valuenow': String(preview), 'aria-valuemin': '0', 'aria-valuemax': '180' })[name];
    } };
}, querySelectorAll() { return []; } };
const video = { duration: 180, currentTime: 10,
    addEventListener() {}, removeEventListener() {} };
globalThis.location = { hash: '#/watch?v=abcdefghijk' };
globalThis.document = {
    documentElement: html, body,
    createElement: tag => new Node(tag),
    querySelector: selector => ({ video, 'div[idomkey="slider"]': slider,
        'ytlr-progress-bar': progress,
        '[idomkey="elapsedTime"]': previewClock })[selector] || null
};

chapterTick();
const overlay = html.children[0];
assert.equal(overlay.id, 'ttcc-chapters');
assert.equal(overlay.querySelectorAll('.ttcc-chapter-tick').length, 2);
assert.equal(overlay.children[0].textContent, 'Test');
slider = new Node('replacement slider');
preview = 130;
chapterTick();
assert.equal(html.children[0], overlay);
assert.equal(html.children.length, 1);
assert.equal(overlay.children[0].textContent, 'Wynik');

// TV seek preview changes while playback is still at 10 seconds and its
// ordinary playhead/ARIA value is stale. The visible preview clock wins.
preview = 65;
chapterTick();
assert.equal(overlay.children[0].textContent, 'Test');
previewClock = { textContent: '2:10' };
onKeydown({ keyCode: 39 });
chapterTick();
assert.equal(video.currentTime, 10);
assert.equal(overlay.children[0].textContent, 'Wynik');
previewClock = null;
preview = 130;
progress.getBoundingClientRect = () => ({ top: 700 });
progress.parentElement = { querySelectorAll: () => [{
    children: [], textContent: '1:05',
    getAttribute: () => 'seek-preview-time',
    getBoundingClientRect: () => ({ top: 680 }),
    parentElement: null
}] };
onKeydown({ keyCode: 37 });
chapterTick();
assert.equal(overlay.children[0].textContent, 'Test');

console.log('Chapter extraction, overlay, and seek-preview checks passed');
