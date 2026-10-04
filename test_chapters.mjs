import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

globalThis.window = {};
globalThis.setInterval = () => 1;
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

console.log('Chapter extraction checks passed');
