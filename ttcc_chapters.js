// Chapter data is consumed from the current TV response where available.
// The WEB next endpoint is queried once per video only if the TV omits it.
const MAX_CACHE = 20;
const chapterCache = new Map();
const requested = new Set();
let currentId = null;
let currentVideo = null;
let currentChapter = -1;
let fetchTimer = null;
let overlay = null;
let titleNode = null;

const at = (object, ...keys) => keys.reduce((value, key) => value && value[key], object);
const textOf = (value) => value?.simpleText || value?.runs?.map(run => run.text || '').join('') || '';

function normalize(items) {
    if (!Array.isArray(items) || items.length < 2 || items.length > 200) return [];
    const chapters = items.map(item => ({
        time: Number(item.time),
        title: String(item.title || '').trim().slice(0, 120)
    })).filter(item => Number.isFinite(item.time) && item.time >= 0 && item.title);
    chapters.sort((a, b) => a.time - b.time);
    return chapters.length >= 2 && chapters[0].time === 0 &&
        chapters.every((item, index) => !index || item.time > chapters[index - 1].time)
        ? chapters : [];
}

export function extractChapters(data) {
    const bar = at(data, 'playerOverlays', 'playerOverlayRenderer',
        'decoratedPlayerBarRenderer', 'decoratedPlayerBarRenderer', 'playerBar');
    const fromBar = at(bar, 'chapteredPlayerBarRenderer', 'chapters');
    if (Array.isArray(fromBar)) {
        const chapters = normalize(fromBar.map(item => ({
            time: Number(at(item, 'chapterRenderer', 'timeRangeStartMillis')) / 1000,
            title: textOf(at(item, 'chapterRenderer', 'title'))
        })));
        if (chapters.length) return chapters;
    }

    const maps = at(bar, 'multiMarkersPlayerBarRenderer', 'markersMap');
    if (Array.isArray(maps)) {
        for (const map of maps) {
            if (map.key !== 'DESCRIPTION_CHAPTERS' && map.key !== 'AUTO_CHAPTERS') continue;
            const markers = at(map, 'value', 'chapters') || at(map, 'value', 'markers');
            const chapters = normalize((markers || []).map(item => ({
                time: Number(item.startMillis) / 1000,
                title: textOf(item.title)
            })));
            if (chapters.length) return chapters;
        }
    }

    for (const panel of data?.engagementPanels || []) {
        const contents = at(panel, 'engagementPanelSectionListRenderer', 'content',
            'macroMarkersListRenderer', 'contents');
        if (!Array.isArray(contents)) continue;
        const chapters = normalize(contents.map(item => {
            const renderer = item.macroMarkersListItemRenderer || {};
            const time = textOf(renderer.timeDescription).split(':').map(Number);
            if (!time.length || time.length > 3 || time.some(n => !Number.isInteger(n) || n < 0)) return {};
            return { time: time.reduce((seconds, part) => seconds * 60 + part, 0),
                title: textOf(renderer.title) };
        }));
        if (chapters.length) return chapters;
    }
    return [];
}

function remember(id, chapters, source) {
    if (!/^[\w-]{11}$/.test(id) || !chapters.length) return;
    chapterCache.delete(id);
    chapterCache.set(id, { chapters, source });
    if (chapterCache.size > MAX_CACHE) chapterCache.delete(chapterCache.keys().next().value);
    if (id === currentId) draw();
}

export function observeChapterResponse(data) {
    if (!data || typeof data !== 'object') return;
    const id = data.videoDetails?.videoId || at(data, 'contents', 'singleColumnWatchNextResults',
        'results', 'results', 'contents', 0, 'itemSectionRenderer', 'contents', 0,
        'videoMetadataRenderer', 'videoId');
    if (typeof id !== 'string' || chapterCache.has(id)) return;
    const chapters = extractChapters(data);
    if (chapters.length) remember(id, chapters, 'tv');
}

function videoId() {
    try {
        const player = document.querySelector('.html5-video-player');
        const id = player?.getVideoData?.()?.video_id;
        if (/^[\w-]{11}$/.test(id || '')) return id;
    } catch (_) {}
    const match = location.hash.match(/[?&]v=([\w-]{11})(?:&|$)/);
    return match ? match[1] : null;
}

async function fetchChapters(id) {
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    const timeout = controller && setTimeout(() => controller.abort(), 5000);
    try {
        const apiKey = window.ytcfg?.get?.('INNERTUBE_API_KEY');
        const url = '/youtubei/v1/next' + (apiKey ? '?key=' + encodeURIComponent(apiKey) : '');
        const response = await fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-YouTube-Client-Name': '1',
                'X-YouTube-Client-Version': '2.20260708.00.00' },
            body: JSON.stringify({ videoId: id, context: { client: {
                clientName: 'WEB', clientVersion: '2.20260708.00.00', hl: 'pl', gl: 'PL'
            } } }),
            ...(controller ? { signal: controller.signal } : {})
        });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const chapters = extractChapters(await response.json());
        if (chapters.length) remember(id, chapters, 'web');
    } catch (error) {
        console.info('TTCC chapters unavailable:', error.message);
    } finally {
        if (timeout) clearTimeout(timeout);
    }
}

function clearOverlay() {
    if (overlay) overlay.remove();
    overlay = null;
    titleNode = null;
    currentChapter = -1;
}

function draw() {
    const record = chapterCache.get(currentId);
    const video = document.querySelector('video');
    const slider = document.querySelector('div[idomkey="slider"]');
    if (!record || !video || !slider || !Number.isFinite(video.duration) || video.duration <= 0) {
        clearOverlay();
        return;
    }
    if (overlay?.parentNode !== slider) clearOverlay();
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'ttcc-chapters';
        overlay.style.cssText = 'position:absolute;left:0;right:0;top:0;bottom:0;pointer-events:none;z-index:12;';
        titleNode = document.createElement('div');
        titleNode.style.cssText = 'position:absolute;left:0;bottom:24px;max-width:55%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;background:rgba(0,0,0,.72);color:#fff;padding:3px 8px;font-size:16px;border-radius:4px;';
        overlay.appendChild(titleNode);
        slider.appendChild(overlay);
    }
    // Rebuild only if the video or its duration changed, never on timeupdate.
    const signature = currentId + ':' + video.duration + ':' + record.chapters.length;
    if (overlay.dataset.signature !== signature) {
        overlay.querySelectorAll('.ttcc-chapter-tick').forEach(node => node.remove());
        for (const chapter of record.chapters.slice(1)) {
            if (chapter.time >= video.duration) continue;
            const tick = document.createElement('span');
            tick.className = 'ttcc-chapter-tick';
            tick.style.cssText = 'position:absolute;top:0;height:100%;width:2px;background:#fff;opacity:.9;';
            tick.style.left = (100 * chapter.time / video.duration) + '%';
            overlay.appendChild(tick);
        }
        overlay.dataset.signature = signature;
        currentChapter = -1;
    }
    updateTitle();
}

function updateTitle() {
    const chapters = chapterCache.get(currentId)?.chapters;
    if (!titleNode || !currentVideo || !chapters) return;
    const time = currentVideo.currentTime;
    let index = 0;
    for (let i = 1; i < chapters.length && chapters[i].time <= time; i++) index = i;
    if (index !== currentChapter) {
        currentChapter = index;
        titleNode.textContent = chapters[index].title;
    }
}

function tick() {
    const id = videoId();
    if (id !== currentId) {
        currentId = id;
        clearOverlay();
        if (fetchTimer) clearTimeout(fetchTimer);
        if (id && !chapterCache.has(id) && !requested.has(id)) {
            fetchTimer = setTimeout(() => {
                if (currentId !== id || chapterCache.has(id)) return;
                requested.add(id);
                if (requested.size > MAX_CACHE) requested.delete(requested.values().next().value);
                fetchChapters(id);
            }, 1800);
        }
    }
    const video = document.querySelector('video');
    if (video !== currentVideo) {
        if (currentVideo) currentVideo.removeEventListener('timeupdate', updateTitle);
        currentVideo = video;
        if (video) video.addEventListener('timeupdate', updateTitle);
        clearOverlay();
    }
    if (id && chapterCache.has(id)) draw();
}

window.ttccChapters = () => ({ videoId: currentId,
    count: chapterCache.get(currentId)?.chapters.length || 0,
    source: chapterCache.get(currentId)?.source || null,
    requested: requested.has(currentId) });
setInterval(tick, 1200);
setTimeout(tick, 1200);
