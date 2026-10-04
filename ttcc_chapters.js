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
let markedSignature = null;
let seekingUntil = 0;
let seekRefreshTimer = null;
let seekFollowupTimer = null;

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
    markedSignature = null;
}

function ensureOverlay() {
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'ttcc-chapters';
        // Incremental DOM regularly replaces the slider's children. Keep the
        // overlay outside that tree to avoid flickering and repeated rebuilds.
        overlay.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483646;display:none;';
        titleNode = document.createElement('div');
        titleNode.style.cssText = 'position:absolute;left:0;bottom:24px;max-width:70%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;background:rgba(0,0,0,.8);color:#fff;padding:5px 10px;font-size:20px;border-radius:5px;';
        overlay.appendChild(titleNode);
        document.documentElement.appendChild(overlay);
    }
}

function visible(element) {
    for (let node = element; node && node !== document.body; node = node.parentElement) {
        const style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) < 0.05) return false;
    }
    return true;
}

function draw() {
    const record = chapterCache.get(currentId);
    const video = currentVideo || document.querySelector('video');
    const slider = document.querySelector('div[idomkey="slider"]');
    if (!record || !video || !slider || !Number.isFinite(video.duration) || video.duration <= 0) {
        if (overlay) overlay.style.display = 'none';
        return;
    }
    ensureOverlay();
    const rect = slider.getBoundingClientRect();
    if (!visible(slider) || rect.width < 100 || rect.height < 1 || rect.top < 0 || rect.top >= window.innerHeight) {
        overlay.style.display = 'none';
        return;
    }
    overlay.style.left = rect.left + 'px';
    overlay.style.top = rect.top + 'px';
    overlay.style.width = rect.width + 'px';
    overlay.style.height = rect.height + 'px';
    overlay.style.display = 'block';

    // YouTube can rebuild its own bar at any time. Our markers are recreated
    // only for a different video or duration, not on each UI repaint.
    const signature = currentId + ':' + video.duration + ':' + record.chapters.length;
    if (markedSignature !== signature) {
        overlay.querySelectorAll('.ttcc-chapter-tick').forEach(node => node.remove());
        for (const chapter of record.chapters.slice(1)) {
            if (chapter.time >= video.duration) continue;
            const tick = document.createElement('span');
            tick.className = 'ttcc-chapter-tick';
            tick.style.cssText = 'position:absolute;top:0;height:100%;width:2px;background:#fff;opacity:.9;';
            tick.style.left = (100 * chapter.time / video.duration) + '%';
            overlay.appendChild(tick);
        }
        markedSignature = signature;
        currentChapter = -1;
    }
    updateTitle();
}

function parseClock(value, duration) {
    if (typeof value !== 'string') return null;
    const parts = value.trim().split('/')[0].trim().split(':');
    if (parts.length < 2 || parts.length > 3 || parts.some(part => !/^\d{1,3}$/.test(part))) return null;
    const seconds = parts.map(Number).reduce((total, part) => total * 60 + part, 0);
    return seconds >= 0 && seconds <= duration + 2 ? seconds : null;
}

function previewTime(video, progress) {
    if (Date.now() >= seekingUntil || !progress) return null;

    // Leanback updates its visible seek clock while the video remains at the
    // old position. Read that clock before looking at the playback playhead.
    const clocks = [
        progress.querySelector('[idomkey="elapsedTime"]'),
        progress.querySelector('[idomkey="previewTime"]'),
        progress.querySelector('[idomkey="seekTime"]'),
        document.querySelector('[idomkey="elapsedTime"]')
    ];
    for (const node of clocks) {
        const time = parseClock(node?.textContent, video.duration);
        if (time !== null && Math.abs(time - video.currentTime) > 1) return time;
    }

    // Preview clocks have changed names across Leanback builds. Inspect only
    // short, visible leaf labels near the progress bar while an arrow is held.
    const labels = progress.parentElement?.querySelectorAll('[idomkey], [class*="Time"]') || [];
    for (const node of labels) {
        if (node.children?.length || /duration/i.test(node.getAttribute('idomkey') || '')) continue;
        const time = parseClock(node.textContent, video.duration);
        if (time === null || Math.abs(time - video.currentTime) <= 1 ||
            Math.abs(time - video.duration) <= 1 || !visible(node)) continue;
        const rect = node.getBoundingClientRect();
        const barTop = progress.getBoundingClientRect().top;
        if (rect.top >= barTop - 250 && rect.top <= barTop + 100) return time;
    }

    // Some Leanback layouts place the thumbnail/preview cursor on the bar
    // rather than exposing a time label. Use its position if it is visible.
    const bar = document.querySelector('div[idomkey="slider"]');
    if (!bar) return null;
    const bounds = bar.getBoundingClientRect();
    if (bounds.width <= 0) return null;
    const cursors = progress.querySelectorAll('[idomkey*="scrub"], [idomkey*="preview"], [class*="Scrubber"], [class*="SeekPreview"]');
    for (const cursor of cursors) {
        const rect = cursor.getBoundingClientRect();
        if (!visible(cursor) || rect.width <= 0 || rect.width > bounds.width / 4) continue;
        const center = rect.left + rect.width / 2;
        if (center < bounds.left - 5 || center > bounds.right + 5) continue;
        const time = video.duration * Math.max(0, Math.min(1, (center - bounds.left) / bounds.width));
        if (Math.abs(time - video.currentTime) > 1) return time;
    }
    return null;
}

function seekTime(video) {
    const progress = document.querySelector('ytlr-progress-bar');
    const preview = previewTime(video, progress);
    if (preview !== null) return preview;
    const control = progress?.querySelector('[role="slider"][aria-valuenow]');
    if (control) {
        const value = Number(control.getAttribute('aria-valuenow'));
        const min = Number(control.getAttribute('aria-valuemin') || 0);
        const max = Number(control.getAttribute('aria-valuemax'));
        if (Number.isFinite(value) && Number.isFinite(max) && max > min && value >= min && value <= max) {
            return video.duration * (value - min) / (max - min);
        }
    }
    const bar = document.querySelector('div[idomkey="slider"]');
    const head = progress?.querySelector('.ytLrProgressBarPlayhead');
    if (bar && head) {
        const b = bar.getBoundingClientRect();
        const h = head.getBoundingClientRect();
        if (b.width > 0 && h.width >= 0 && h.left >= b.left - 5 && h.left <= b.right + 5) {
            return video.duration * Math.max(0, Math.min(1, (h.left + h.width / 2 - b.left) / b.width));
        }
    }
    return video.currentTime;
}

function updateTitle() {
    const chapters = chapterCache.get(currentId)?.chapters;
    if (!titleNode || !currentVideo || !chapters) return;
    const time = seekTime(currentVideo);
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

// During remote-control seeking, the preview can move before <video>
// emits timeupdate. Read the progress control after the arrow has been handled.
window.addEventListener('keydown', event => {
    const code = event.keyCode || event.which;
    if (code === 13 || code === 27 || code === 10009) {
        seekingUntil = 0;
        return;
    }
    if (code !== 37 && code !== 39) return;
    seekingUntil = Date.now() + 2200;
    if (seekRefreshTimer) clearTimeout(seekRefreshTimer);
    if (seekFollowupTimer) clearTimeout(seekFollowupTimer);
    seekRefreshTimer = setTimeout(updateTitle, 80);
    seekFollowupTimer = setTimeout(updateTitle, 300);
}, true);

window.ttccChapters = () => ({ videoId: currentId,
    count: chapterCache.get(currentId)?.chapters.length || 0,
    source: chapterCache.get(currentId)?.source || null,
    requested: requested.has(currentId) });
setInterval(tick, 1200);
setTimeout(tick, 1200);
