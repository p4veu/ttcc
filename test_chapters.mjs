import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

let chapterTick;
globalThis.window = {
    innerHeight: 1080,
    addEventListener() {},
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
const progress = { querySelector(selector) {
    if (selector !== '[role="slider"][aria-valuenow]') return null;
    return { getAttribute(name) {
        return ({ 'aria-valuenow': String(preview), 'aria-valuemin': '0', 'aria-valuemax': '180' })[name];
    } };
} };
const video = { duration: 180, currentTime: 10,
    addEventListener() {}, removeEventListener() {} };
globalThis.location = { hash: '#/watch?v=abcdefghijk' };
globalThis.document = {
    documentElement: html, body,
    createElement: tag => new Node(tag),
    querySelector: selector => ({ video, 'div[idomkey="slider"]': slider,
        'ytlr-progress-bar': progress })[selector] || null
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

console.log('Chapter extraction and persistent overlay checks passed');
