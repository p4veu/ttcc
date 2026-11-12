from pathlib import Path
import sys

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("upstream")

def replace_once(path, old, new, label):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match in {path}, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

# Guard against TizenBrew's first asynchronous injection arriving after YouTube started.
# On that first late injection, reload once. TizenBrew has cached the userscript by then,
# so the next document receives it immediately, before YouTube initializes its ad pipeline.
startup_guard = r"""
(function () {
    const host = String(window.location.hostname || '').toLowerCase();
    if (host !== 'youtube.com' && host !== 'www.youtube.com') return;

    const key = '__ttcc_startup_retry_v1';
    let storage = null;
    try {
        storage = window.sessionStorage;
    } catch (_) {
        return;
    }
    if (!storage) return;

    let previousRetry = 0;
    try {
        previousRetry = Number(storage.getItem(key)) || 0;
    } catch (_) {
        return;
    }

    const pageAlreadyStarted =
        document.readyState !== 'loading' ||
        !!window._yttv ||
        !!(window.yt && window.yt.config_) ||
        !!window.ytInitialData ||
        !!document.querySelector('video');

    if (pageAlreadyStarted) {
        const now = Date.now();
        if (!previousRetry || now - previousRetry > 30000) {
            try {
                storage.setItem(key, String(now));
            } catch (_) {
                return;
            }
            console.warn('TTCC: late TizenBrew injection detected; restarting once for early ad-block initialization.');
            window.location.reload();
            throw new Error('TTCC_STARTUP_RELOAD_ONCE');
        }
    } else if (previousRetry) {
        // The retry reached a new document early enough; allow future startup repairs.
        try {
            storage.removeItem(key);
        } catch (_) {}
    }
})();
"""

standalone = ROOT / "mods/features/standaloneUserscript.js"
standalone_text = standalone.read_text(encoding="utf-8")
if "__ttcc_startup_retry_v1" in standalone_text:
    raise SystemExit("startup guard already present in standaloneUserscript.js")
standalone.write_text(startup_guard + "\n" + standalone_text, encoding="utf-8")

# Build from the clean upstream TizenTube 1.15.0 source and change only:
# 1) guarded one-time retry when the first TizenBrew injection is late,
# 2) direct Screen Off button placement,
# 3) Screen Off wake-up behavior,
# 4) DIAL/casting target.

custom_ui = ROOT / "mods/ui/customUI.js"
text = custom_ui.read_text(encoding="utf-8")

setting_marker = """        const settingActionGroup = functions.find(func => {
            return func.rhs.includes('TRANSPORT_CONTROLS_BUTTON_TYPE_PLAYBACK_SETTINGS');
        }).left.split('.')[1];"""

screen_command = """        const screenOffCommand = {
            "type": "TRANSPORT_CONTROLS_BUTTON_TYPE_TURN_OFF_SCREEN",
            "button": {
                "buttonRenderer": ButtonRenderer(
                    false,
                    t('player.screenOff'),
                    'EYE_OFF',
                    {
                        customAction: {
                            action: 'SCREEN_OFF',
                        }
                    }
                )
            }
        }

"""
if text.count(setting_marker) != 1:
    raise SystemExit("customUI: playback-settings marker changed upstream")
text = text.replace(setting_marker, screen_command + setting_marker, 1)

# Keep the official Mini Player patch untouched. On this TV its action group
# is not producing the small direct buttons, so Screen Off is injected into
# engagementActions instead (the same group used by TizenTube's speed button).
# Insert our wrapper LAST so it wraps all upstream engagement-action filters.
prev_next_marker = """        if (configRead('enablePreviousNextButtons')) {"""

screen_wrapper = """        if (engagementActionButton) {
            const origScreenOffActionButton = inst[engagementActionButton];
            if (typeof origScreenOffActionButton === 'function') {
                inst[engagementActionButton] = function () {
                    const res = origScreenOffActionButton.apply(this, arguments);
                    if (!Array.isArray(res)) return res;

                    // Leanback returns empty placeholder items while its
                    // control row is loading. Only attach our button after a
                    // real native action with a renderer is present. A speed
                    // button alone would create a focusable synthetic row.
                    const hasNativeAction = res.some(item => item && item.type &&
                        item.type !== 'TRANSPORT_CONTROLS_BUTTON_TYPE_SPEED' &&
                        item.type !== 'TRANSPORT_CONTROLS_BUTTON_TYPE_TURN_OFF_SCREEN' &&
                        item.button && item.button.buttonRenderer);
                    if (!hasNativeAction) return res.filter(item => item &&
                        item.type !== 'TRANSPORT_CONTROLS_BUTTON_TYPE_SPEED' &&
                        item.type !== 'TRANSPORT_CONTROLS_BUTTON_TYPE_TURN_OFF_SCREEN');

                    if (!res.find(item => item && item.type === 'TRANSPORT_CONTROLS_BUTTON_TYPE_TURN_OFF_SCREEN')) {
                        res.unshift(screenOffCommand);
                    }

                    return res;
                };
            }
        }

"""
if text.count(prev_next_marker) != 1:
    raise SystemExit("customUI: previous/next marker changed upstream")
text = text.replace(prev_next_marker, screen_wrapper + prev_next_marker, 1)
custom_ui.write_text(text, encoding="utf-8")

# Replace upstream SCREEN_OFF implementation. Upstream hides every body child
# and ui.js later restores every one with display:block, which can expose the
# normally hidden Theme Configuration panel.
replace_once(
    "mods/resolveCommand.js",
    "import checkForUpdates from './features/updater.js';",
    "import checkForUpdates from './features/updater.js';\nimport { turnOffScreen } from './features/turnOffScreen.js';",
    "resolveCommand import"
)

old_screen = """        case 'SCREEN_OFF':
            for (const child of document.body.children) {
                if (child.tagName.toLowerCase() === 'script' || child.tagName.toLowerCase() === 'svg') continue;
                child.style.setProperty('display', 'none', 'important');
            }
            window.screenTurnedOffAt = Date.now();
            break;"""
new_screen = """        case 'SCREEN_OFF':
            turnOffScreen();
            break;"""
replace_once("mods/resolveCommand.js", old_screen, new_screen, "SCREEN_OFF implementation")

turn_off = r"""let cleanupWakeGuard = null;

function swallow(event) {
    try { event.preventDefault(); } catch (_) {}
    try { event.stopPropagation(); } catch (_) {}
    try {
        if (event.stopImmediatePropagation) event.stopImmediatePropagation();
    } catch (_) {}
}

function ensureBlackoutStyle() {
    let style = document.getElementById('__ttcc_screen_off_style');
    if (style) return;

    style = document.createElement('style');
    style.id = '__ttcc_screen_off_style';
    style.textContent = [
        'html[data-ttcc-screen-off="1"]::after {',
        'content: "";',
        'position: fixed;',
        'left: 0;',
        'top: 0;',
        'right: 0;',
        'bottom: 0;',
        'width: 100vw;',
        'height: 100vh;',
        'margin: 0;',
        'padding: 0;',
        'background: #000;',
        'z-index: 2147483647;',
        'pointer-events: none;',
        '}'
    ].join('');
    (document.head || document.documentElement).appendChild(style);
}

function setBlackout(active) {
    if (active) {
        document.documentElement.setAttribute('data-ttcc-screen-off', '1');
    } else {
        document.documentElement.removeAttribute('data-ttcc-screen-off');
    }
}

export function turnOffScreen() {
    if (cleanupWakeGuard) {
        cleanupWakeGuard();
        cleanupWakeGuard = null;
    }

    setBlackout(false);

    // Never use TizenTube's stock screenTurnedOffAt wake path. Its ui.js
    // restores every body child with display:block and can show Theme Config.
    window.screenTurnedOffAt = null;

    // Keep the blackout outside YouTube's body DOM. When playback resumes,
    // Leanback can rebuild parts of the body and remove injected elements.
    // A CSS pseudo-element attached to <html> survives those rerenders.
    ensureBlackoutStyle();
    setBlackout(true);

    let waking = false;
    let wakeKeyCode = 0;
    let fallbackTimer = null;
    let mediaPassThroughUntil = 0;
    const types = ['keydown', 'keypress', 'keyup'];

    // SCREEN_OFF is normally invoked by pressing OK. The keyup from THAT SAME
    // press arrives after the overlay is created. v1 treated it as a wake key,
    // so the picture came back immediately. Swallow the tail of the activation
    // key for a short grace period, then arm normal wake-up.
    const armAt = Date.now() + 600;

    const cleanup = () => {
        for (const type of types) {
            window.removeEventListener(type, wakeGuard, true);
        }
        if (fallbackTimer) {
            clearTimeout(fallbackTimer);
            fallbackTimer = null;
        }
        if (cleanupWakeGuard === cleanup) cleanupWakeGuard = null;
    };

    const wakeGuard = (event) => {
        // Window capture runs before TizenTube's document-capture handlers.
        const now = Date.now();
        const code = event.keyCode || event.which || 0;
        const key = event.key || '';

        // TTCC v4: Play/Pause must control playback without waking the picture.
        // Some Samsung firmware emits a valid media keydown followed by a
        // keypress/keyup with code 0 (or another translated tail event). v3
        // passed the first event through but interpreted that tail as "wake".
        // Once a media key is seen, pass the whole short event sequence through.
        const isMediaPlayPause =
            code === 10252 || code === 415 || code === 19 ||
            key === 'MediaPlayPause' || key === 'MediaPlay' || key === 'MediaPause';

        if (isMediaPlayPause) {
            mediaPassThroughUntil = now + 900;
            return true;
        }

        if (now < mediaPassThroughUntil) {
            return true;
        }

        // Every other key belongs to the Screen Off wake sequence.
        swallow(event);

        if (now < armAt) {
            return false;
        }

        if (!waking) {
            waking = true;
            wakeKeyCode = code;
            setBlackout(false);

            // Fallback for Samsung firmware/remotes that do not emit keyup.
            fallbackTimer = setTimeout(cleanup, 900);
        }

        if (event.type === 'keyup' && (!wakeKeyCode || !code || code === wakeKeyCode)) {
            cleanup();
        }

        return false;
    };

    cleanupWakeGuard = cleanup;
    for (const type of types) {
        window.addEventListener(type, wakeGuard, true);
    }
}

export function turnOnScreen() {
    if (cleanupWakeGuard) {
        cleanupWakeGuard();
        cleanupWakeGuard = null;
    }
    setBlackout(false);
    window.screenTurnedOffAt = null;
}
"""
(ROOT / "mods/features/turnOffScreen.js").write_text(turn_off, encoding="utf-8")

# Polish label used by both the existing More settings item and direct button.
pl = ROOT / "mods/translations/resources/pl.json"
pl_text = pl.read_text(encoding="utf-8")
if '"screenOff": "Turn off screen"' in pl_text:
    pl.write_text(pl_text.replace('"screenOff": "Turn off screen"', '"screenOff": "Wyłącz ekran"', 1), encoding="utf-8")

# Casting/DIAL must reopen this GitHub module, not the upstream npm module.
replace_once(
    "service/service.js",
    "moduleName: '@foxreis/tizentube',",
    "moduleName: 'p4veu/ttcc',",
    "DIAL module name"
)
replace_once(
    "service/service.js",
    "moduleType: 'npm',",
    "moduleType: 'gh',",
    "DIAL module type"
)

print("TTCC v5 patch applied successfully")


# Experimental HA search + screen-control bridge. Published to existing gh/p4veu/ttcc.
# The confirmed working .5 remains frozen in stable-fully-working-ttcc-1.15.0-ttcc.5.
replace_once(
    "service/service.js",
    "const PORT = global.isTizenTube ? 8095 : 8085;",
    "const PORT = 8096;",
    "HA test service port"
)

service_path = ROOT / "service/service.js"
service_source = service_path.read_text(encoding="utf-8")
service_marker = "app.use(cors(corsOptions));"
ha_service = r"""
app.use(express.json({ limit: '2kb' }));

let haPendingSearch = null;
let haLastPoll = 0;
let haSearchNumber = 0;
let haHidden = null;
let haFocused = null;
let haVisibilityState = null;
let haScreenOff = null;
let haAutoScreenOffArmed = null;
let haVideo = null;
let haResume = null;

// Minimal read-only health check: usable from any phone on the LAN.
app.get('/ttcc/status', (req, res) => {
    res.json({
        ok: true,
        version: '1.15.4',
        connected: haLastPoll > 0 && (Date.now() - haLastPoll) < 7000,
        hidden: haHidden,
        focused: haFocused,
        visibilityState: haVisibilityState,
        screenOff: haScreenOff,
        autoScreenOffArmed: haAutoScreenOffArmed,
        video: haVideo,
        resume: haResume,
        pending: !!haPendingSearch
    });
});

// HA will POST {"query":"Metallica"} to the TV.
app.post('/ttcc/search', (req, res) => {
    const input = req.body && req.body.query;
    if (typeof input !== 'string') {
        return res.status(400).json({ ok: false, error: 'query must be a string' });
    }
    const query = input.trim();
    if (query.length < 1 || query.length > 160) {
        return res.status(400).json({ ok: false, error: 'query must be 1-160 chars' });
    }
    haPendingSearch = { id: ++haSearchNumber, query, autoScreenOff: req.body.auto_screen_off === true };
    return res.json({ ok: true, queued: true, id: haPendingSearch.id });
});

// HA will POST {"playlist_id":"PL..."} to open and start a playlist on the TV.
app.post('/ttcc/playlist', (req, res) => {
    const input = req.body && req.body.playlist_id;
    if (typeof input !== 'string') {
        return res.status(400).json({ ok: false, error: 'playlist_id must be a string' });
    }
    const playlistId = input.trim();
    if (!/^[A-Za-z0-9_-]{10,120}$/.test(playlistId)) {
        return res.status(400).json({ ok: false, error: 'invalid playlist_id' });
    }
    haPendingSearch = { id: ++haSearchNumber, playlistId };
    return res.json({ ok: true, queued: true, id: haPendingSearch.id });
});

// Manual HA Assist screen control. These commands use the same poll/ack bridge.
app.post('/ttcc/screen', (req, res) => {
    const state = req.body && req.body.state;
    if (state !== 'on' && state !== 'off') {
        return res.status(400).json({ ok: false, error: 'state must be on or off' });
    }
    haPendingSearch = { id: ++haSearchNumber, screen: state };
    return res.json({ ok: true, queued: true, id: haPendingSearch.id });
});

// YouTube is a remote https page. It polls this local bridge while TTCC runs.
app.get('/ttcc/next', (req, res) => {
    haLastPoll = Date.now();
    haHidden = req.query.hidden === '1' ? true : req.query.hidden === '0' ? false : null;
    haFocused = req.query.focus === '1' ? true : req.query.focus === '0' ? false : null;
    haVisibilityState = typeof req.query.visibility === 'string'
        ? req.query.visibility.slice(0, 32) : null;
    haScreenOff = req.query.black === '1' ? true : req.query.black === '0' ? false : null;
    haAutoScreenOffArmed = req.query.armed === '1' ? true : req.query.armed === '0' ? false : null;
    haVideo = {
        paused: req.query.vp === '1' ? true : req.query.vp === '0' ? false : null,
        readyState: /^[0-4]$/.test(req.query.vr || '') ? Number(req.query.vr) : null,
        time: /^[0-9]+(?:[.][0-9]+)?$/.test(req.query.vt || '') ? Number(req.query.vt) : null,
        error: /^[0-4]$/.test(req.query.ve || '') ? Number(req.query.ve) : null
    };
    haResume = {
        stage: typeof req.query.rs === 'string' ? req.query.rs.slice(0, 32) : null,
        events: /^\d+$/.test(req.query.re || '') ? Number(req.query.re) : null,
        videoId: /^[\w-]{11}$/.test(req.query.ri || '') ? req.query.ri : null
    };
    return res.json(haPendingSearch
        ? { pending: true, command: haPendingSearch }
        : { pending: false });
});

// Clear only after YouTube has attempted to navigate to the search results.
app.post('/ttcc/ack', (req, res) => {
    const id = req.body && Number(req.body.id);
    if (haPendingSearch && id === haPendingSearch.id) {
        haPendingSearch = null;
        return res.json({ ok: true });
    }
    return res.status(409).json({ ok: false, error: 'command no longer pending' });
});
"""
if service_source.count(service_marker) != 1:
    raise SystemExit("HA search service marker changed")
service_path.write_text(service_source.replace(service_marker, service_marker + "\n" + ha_service, 1), encoding="utf-8")

# Use the same command path as the built-in Search page, but with a spoken query.
# This is intentionally a separate feature: none of the working Screen Off code is touched.
ha_client = r"""import resolveCommand from '../resolveCommand.js';
import { turnOffScreen, turnOnScreen } from './turnOffScreen.js';

const HA_BRIDGE = 'http://127.0.0.1:8096/ttcc';
let pollInProgress = false;
let autoScreenOffArmed = false;
let videoIdAtSearch = null;
let autoOffExpires = 0;
let pendingAutoOffTimer = null;

function getPlaybackInfo() {
    try {
        const player = document.querySelector('.html5-video-player');
        const state = player && player.getPlayerStateObject && player.getPlayerStateObject();
        const data = player && player.getVideoData && player.getVideoData();
        return { playing: !!(state && state.isPlaying), id: data && data.video_id || null };
    } catch (e) {
        return { playing: false, id: null };
    }
}

function cancelAutoScreenOff() {
    autoScreenOffArmed = false;
    videoIdAtSearch = null;
    if (pendingAutoOffTimer) {
        clearTimeout(pendingAutoOffTimer);
        pendingAutoOffTimer = null;
    }
}

function armAutoScreenOffAfterSearch() {
    cancelAutoScreenOff();
    videoIdAtSearch = getPlaybackInfo().id;
    autoOffExpires = Date.now() + 10 * 60 * 1000;
    autoScreenOffArmed = true;
}

// Keep displaying search results. Only darken AFTER a different selected
// video begins playing (not when the OK button is pressed on a result).
function watchForSelectedVideo() {
    if (!autoScreenOffArmed) return;
    if (Date.now() >= autoOffExpires) {
        cancelAutoScreenOff();
        return;
    }
    const info = getPlaybackInfo();
    if (!info.playing || !info.id || info.id === videoIdAtSearch) return;
    autoScreenOffArmed = false;
    const selectedId = info.id;
    pendingAutoOffTimer = setTimeout(function () {
        pendingAutoOffTimer = null;
        const current = getPlaybackInfo();
        if (current.playing && current.id === selectedId) {
            turnOffScreen();
        }
    }, 1000);
}
setInterval(watchForSelectedVideo, 300);

function youtubeSearchReady() {
    if (!window._yttv) return false;
    for (const key in window._yttv) {
        const entry = window._yttv[key];
        if (entry && entry.instance && typeof entry.instance.resolveCommand === 'function') {
            return true;
        }
    }
    return false;
}

function pollHaSearch() {
    if (pollInProgress || !youtubeSearchReady()) return;
    pollInProgress = true;

    const focus = typeof document.hasFocus === 'function'
        ? (document.hasFocus() ? '1' : '0') : 'unknown';
    const visibility = encodeURIComponent(document.visibilityState || 'unknown');
    const video = document.querySelector('video');
    const flags = '&hidden=' + (document.hidden ? '1' : '0') +
                  '&focus=' + focus + '&visibility=' + visibility +
                  '&black=' + (document.documentElement.getAttribute('data-ttcc-screen-off') === '1' ? '1' : '0') +
                  '&armed=' + (autoScreenOffArmed ? '1' : '0') +
                  (window.ttccResumeState ?
                    '&rs=' + encodeURIComponent(window.ttccResumeState.stage || '') +
                    '&re=' + (window.ttccResumeState.events || 0) +
                    '&ri=' + encodeURIComponent(window.ttccResumeState.videoId || '') : '') +
                  (video ? '&vp=' + (video.paused ? '1' : '0') +
                    '&vr=' + video.readyState +
                    '&vt=' + (Number.isFinite(video.currentTime) ? video.currentTime.toFixed(1) : '') +
                    '&ve=' + (video.error ? video.error.code : '0') : '');
    fetch(HA_BRIDGE + '/next?t=' + Date.now() + flags, { cache: 'no-store' })
        .then(function (response) {
            if (!response.ok) throw new Error('HA bridge status: ' + response.status);
            return response.json();
        })
        .then(function (data) {
            if (!data || !data.pending || !data.command) return null;
            const command = data.command;
            if (command.screen === 'on') {
                cancelAutoScreenOff();
                turnOnScreen();
            } else if (command.screen === 'off') {
                cancelAutoScreenOff();
                turnOffScreen();
            } else if (typeof command.playlistId === 'string' && command.playlistId.trim()) {
                // Open the exact playlist using YouTube's playlist browse endpoint.
                turnOnScreen();
                cancelAutoScreenOff();
                const playlistId = command.playlistId.trim();
                resolveCommand({ browseEndpoint: { browseId: 'VL' + playlistId } });

                // YouTube TV normally focuses Play all / the first item on entry.
                // Press Enter shortly afterwards so a voice command starts playback.
                setTimeout(function () {
                    try {
                        const down = document.createEvent('Event');
                        down.initEvent('keydown', true, true);
                        down.keyCode = 13;
                        down.which = 13;
                        document.dispatchEvent(down);

                        const up = document.createEvent('Event');
                        up.initEvent('keyup', true, true);
                        up.keyCode = 13;
                        up.which = 13;
                        document.dispatchEvent(up);
                    } catch (e) {
                        console.warn('TTCC playlist autoplay: ' + e.message);
                    }
                }, 1400);
            } else if (typeof command.query === 'string' && command.query.trim()) {
                // Reveal any currently blackened screen to show the results.
                turnOnScreen();
                cancelAutoScreenOff();
                if (command.autoScreenOff === true) armAutoScreenOffAfterSearch();
                resolveCommand({ searchEndpoint: { query: command.query } });
            } else {
                return null;
            }

            return fetch(HA_BRIDGE + '/ack', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: command.id })
            });
        })
        .catch(function (error) {
            console.warn('TTCC HA Search test: ' + error.message);
        })
        .then(function () {
            pollInProgress = false;
        });
}

setInterval(pollHaSearch, 1400);
setTimeout(pollHaSearch, 2000);
"""
(ROOT / "mods/features/haSearch.js").write_text(ha_client, encoding="utf-8")

entry = ROOT / "mods/userScript.js"
entry_text = entry.read_text(encoding="utf-8")
entry_text += "\nimport './features/haSearch.js';\nimport './features/resumePlayback.js';\n"
entry.write_text(entry_text, encoding="utf-8")

resume_playback = r"""// Tizen can leave the player alive but stop its media pipeline after an app switch.
// Recover on lifecycle events, and use a watchdog when Samsung omits those events.
import resolveCommand from '../resolveCommand.js';

const RECOVERY_KEY = '__ttcc_resume_once';
let playbackBeforeHide = null;
let recentPlayback = null;
let backgroundPause = null;
let hiddenAt = null;
let lastPlaybackControlAt = 0;
let intentionalPauseId = null;
let recoveryTimer = null;
let recoveryAttempted = false;
let lastResumeAt = 0;
let lastWatchdogAt = Date.now();
let lastProgressAt = 0;
let lastObservedVideoId = null;
let lastObservedTime = null;
let lastConfirmedTime = null;
let lastFocusState = typeof document.hasFocus === 'function' ? document.hasFocus() : null;
const resumeState = window.ttccResumeState = { stage: 'loaded', events: 0, videoId: null };

function video() {
    return document.querySelector('video');
}

function videoId() {
    try {
        const player = document.querySelector('.html5-video-player');
        const id = player && player.getVideoData && player.getVideoData().video_id;
        if (/^[\w-]{11}$/.test(id || '')) return id;
    } catch (_) {}
    const match = location.hash.match(/[?&]v=([\w-]{11})(?:&|$)/);
    if (match) return match[1];
    try {
        const id = window.ttccChapters && window.ttccChapters().videoId;
        if (/^[\w-]{11}$/.test(id || '')) return id;
    } catch (_) {}
    return null;
}

function markPlaybackControl(event) {
    const now = Date.now();
    if (event.type === 'keydown') {
        const code = event.keyCode || event.which || 0;
        const key = event.key || '';
        const active = document.activeElement;
        const label = active
            ? String((active.getAttribute && (active.getAttribute('aria-label') || active.getAttribute('title'))) ||
                active.className || '')
            : '';
        const focusedPlaybackButton = /play|pause|odtwórz|odtworz|wstrzymaj/i.test(label);
        if (code === 10252 || code === 415 || code === 19 ||
            key === 'MediaPlayPause' || key === 'MediaPlay' || key === 'MediaPause' ||
            code === 32 || key === ' ' ||
            ((code === 13 || key === 'Enter') && focusedPlaybackButton)) {
            lastPlaybackControlAt = now;
        }
        return;
    }
    const target = event.target && event.target.closest
        ? event.target.closest('video,button,[role="button"]') : null;
    if (!target) return;
    const label = [
        target.getAttribute && target.getAttribute('aria-label'),
        target.getAttribute && target.getAttribute('title'),
        target.className,
        target.textContent
    ].filter(Boolean).join(' ');
    if ((target.tagName && target.tagName.toLowerCase() === 'video') ||
        /play|pause|odtwórz|odtworz|wstrzymaj/i.test(label)) {
        lastPlaybackControlAt = now;
    }
}

['keydown', 'click', 'pointerdown', 'touchstart'].forEach(function (type) {
    window.addEventListener(type, markPlaybackControl, true);
});

function notePlaybackProgress(event) {
    const current = event.target;
    if (current !== video() || current.paused || current.ended) return;
    const id = videoId();
    if (!id || !Number.isFinite(current.currentTime)) return;

    const now = Date.now();
    const time = current.currentTime;
    const previousId = lastObservedVideoId;
    const previousTime = lastObservedTime;
    const idChanged = previousId !== id;
    const movedForward = previousTime === null || time > previousTime + 0.1;
    const jumped = previousTime !== null && Math.abs(time - previousTime) > 2;

    if (!idChanged && !movedForward && !jumped) return;

    if (previousId !== null && idChanged) {
        recoveryAttempted = false;
        intentionalPauseId = null;
        backgroundPause = null;
    } else if (jumped) {
        recoveryAttempted = false;
        lastConfirmedTime = time;
    } else if (idChanged || lastConfirmedTime === null) {
        lastConfirmedTime = time;
    } else if (time > lastConfirmedTime + 0.5) {
        lastConfirmedTime = time;
        recoveryAttempted = false;
    }

    lastObservedVideoId = id;
    lastObservedTime = time;
    lastProgressAt = now;
    recentPlayback = { element: current, id: id, time: time, at: now };
}

function notePlaybackStart(event) {
    const current = event.target;
    if (current !== video() || current.ended) return;
    const id = videoId();
    if (!id || !Number.isFinite(current.currentTime)) return;

    const now = Date.now();
    if (lastObservedVideoId !== null && lastObservedVideoId !== id) {
        recoveryAttempted = false;
        lastConfirmedTime = current.currentTime;
    }
    if (lastObservedVideoId !== id) {
        lastObservedVideoId = id;
        lastObservedTime = current.currentTime;
    }
    if (lastConfirmedTime === null) lastConfirmedTime = current.currentTime;
    lastProgressAt = now;
    recentPlayback = { element: current, id: id, time: current.currentTime, at: now };
    backgroundPause = null;
    intentionalPauseId = null;
}

function notePlaybackPause(event) {
    const current = event.target;
    if (current !== video() || current.ended) return;
    const id = videoId();
    const now = Date.now();
    if (!id || !recentPlayback || recentPlayback.id !== id ||
        now - recentPlayback.at > 15000) return;
    if (now - lastPlaybackControlAt <= 2500) {
        intentionalPauseId = id;
        backgroundPause = null;
        return;
    }
    if (intentionalPauseId === id) return;
    backgroundPause = {
        element: current,
        id: id,
        time: Number.isFinite(current.currentTime) ? current.currentTime : recentPlayback.time,
        at: now
    };
    resumeState.stage = 'pause-candidate';
    resumeState.videoId = id;
}

document.addEventListener('timeupdate', notePlaybackProgress, true);
document.addEventListener('play', notePlaybackStart, true);
document.addEventListener('playing', notePlaybackStart, true);
document.addEventListener('pause', notePlaybackPause, true);
document.addEventListener('play', notePlaybackStart, true);
document.addEventListener('playing', notePlaybackStart, true);

function clearRecovery() {
    if (recoveryTimer) clearTimeout(recoveryTimer);
    recoveryTimer = null;
}

function youtubeReady() {
    if (!window._yttv) return false;
    for (const key in window._yttv) {
        const entry = window._yttv[key];
        if (entry && entry.instance && typeof entry.instance.resolveCommand === 'function') {
            return true;
        }
    }
    return false;
}

function restoreAfterReload() {
    let snapshot = null;
    try {
        snapshot = JSON.parse(sessionStorage.getItem(RECOVERY_KEY));
        sessionStorage.removeItem(RECOVERY_KEY);
    } catch (_) {}
    if (!snapshot || !/^[\w-]{11}$/.test(snapshot.id) ||
        Date.now() - snapshot.at > 90000) return;

    // Do not loop on reload if the TV's media service has not recovered yet.
    // Actual forward progress or selecting a different video re-arms recovery.
    recoveryAttempted = true;
    resumeState.stage = 'restore-wait';
    resumeState.videoId = snapshot.id;

    let tries = 0;
    const wait = setInterval(function () {
        if (++tries > 80) return clearInterval(wait);
        if (!youtubeReady() || !video()) return;
        clearInterval(wait);
        setTimeout(function () {
            const current = video();
            const initialTime = current ? current.currentTime : 0;
            setTimeout(function () {
                if (document.hidden || !youtubeReady()) return;
                if (videoId() === snapshot.id && video() === current &&
                    current.currentTime > initialTime + 0.5) {
                    resumeState.stage = 'restored-playing';
                    recoveryAttempted = false;
                    return;
                }
                resumeState.stage = 'restore-navigate';
                const watchEndpoint = { videoId: snapshot.id };
                if (Number.isFinite(snapshot.time) && snapshot.time > 0) {
                    watchEndpoint.startTimeSeconds = Math.floor(snapshot.time);
                }
                resolveCommand({ watchEndpoint: watchEndpoint });
            }, 3000);
        }, 4000);
    }, 300);
}

function reloadStalledPlayer(snapshot) {
    if (recoveryAttempted || document.hidden) return;
    recoveryAttempted = true;
    clearRecovery();
    try {
        if (snapshot.id) sessionStorage.setItem(RECOVERY_KEY,
            JSON.stringify({ id: snapshot.id, time: snapshot.time, at: Date.now() }));
    } catch (_) {}
    console.warn('TTCC AutoRecover: playback stalled after app resume; refreshing player');
    resumeState.stage = 'reload-stalled';
    window.location.reload();
}

function checkProgress(snapshot, originalVideo, initialTime) {
    clearRecovery();
    recoveryTimer = setTimeout(function () {
        recoveryTimer = null;
        if (document.hidden || video() !== originalVideo ||
            videoId() !== snapshot.id) return;
        if (originalVideo.currentTime > initialTime + 0.5) {
            resumeState.stage = 'playing';
            recoveryAttempted = false;
            return;
        }
        // Retry play once, then refresh the YouTube player if the stream is still frozen.
        try {
            const result = originalVideo.play();
            if (result && result.catch) result.catch(function () {});
        } catch (_) {}
        recoveryTimer = setTimeout(function () {
            recoveryTimer = null;
            if (!document.hidden && video() === originalVideo &&
                videoId() === snapshot.id &&
                originalVideo.currentTime <= initialTime + 0.5) {
                reloadStalledPlayer(snapshot);
            }
        }, 7000);
    }, 5000);
}

function rememberBeforeHide() {
    const now = Date.now();
    if (hiddenAt === null) hiddenAt = now;

    const current = video();
    const id = videoId();
    const wasPlaying = current && !current.paused && !current.ended;
    if (wasPlaying && id) {
        playbackBeforeHide = { element: current, id: id, time: current.currentTime, at: now };
    } else if (current && intentionalPauseId !== id && recentPlayback && recentPlayback.element === current &&
        recentPlayback.id === id && now - recentPlayback.at < 5000) {
        // Tizen sometimes pauses the media element before reporting that the app was hidden.
        playbackBeforeHide = {
            element: current, id: id, time: current.currentTime, at: recentPlayback.at
        };
    }

    // Do not pause here: pressing HOME only backgrounds the app on Samsung TVs.
    // Preserve the playing session and let Tizen decide whether playback continues.
    resumeState.stage = playbackBeforeHide ? 'hidden-saved' : 'hidden-no-snapshot';
    resumeState.videoId = id;
}

function handleVisibilityChange() {
    if (document.hidden) {
        resumeState.events++;
        clearRecovery();
        rememberBeforeHide();
        return;
    }

    // focus/pageshow can arrive without visibilitychange or blur on some TVs.
    // Infer a suspended playback only if it was recently advancing and there
    // was no explicit user pause.
    const now = Date.now();
    if (!playbackBeforeHide && hiddenAt === null && !backgroundPause) {
        const current = video();
        const id = videoId();
        if (current && id && current.paused && !current.ended &&
            recentPlayback && recentPlayback.id === id &&
            now - recentPlayback.at < 120000 && intentionalPauseId !== id &&
            now - lastPlaybackControlAt > 2500) {
            backgroundPause = {
                element: current, id: id,
                time: Number.isFinite(current.currentTime) ? current.currentTime : recentPlayback.time,
                at: recentPlayback.at
            };
            hiddenAt = recentPlayback.at;
            resumeState.stage = 'focus-paused-detected';
        } else {
            return;
        }
    }

    resumeState.events++;
    clearRecovery();
    const hiddenDuration = hiddenAt === null
        ? (backgroundPause ? now - backgroundPause.at : 0)
        : now - hiddenAt;
    const snapshot = playbackBeforeHide || backgroundPause;
    playbackBeforeHide = null;
    backgroundPause = null;
    hiddenAt = null;
    resumeState.stage = snapshot ? 'visible-saved' : 'visible-no-snapshot';
    if (!snapshot || !snapshot.id || intentionalPauseId === snapshot.id) return;

    lastResumeAt = now;
    if (recoveryAttempted) return;

    // A long standby can leave the old media element permanently detached from the stream.
    if (hiddenDuration >= 30000) {
        resumeState.stage = 'standby-reload-wait';
        recoveryTimer = setTimeout(function () {
            recoveryTimer = null;
            if (!document.hidden && videoId() === snapshot.id) {
                reloadStalledPlayer(snapshot);
            }
        }, 1500);
        return;
    }

    recoveryTimer = setTimeout(function () {
        recoveryTimer = null;
        const current = video();
        if (document.hidden || !current || videoId() !== snapshot.id) return;
        resumeState.stage = 'resume-play';
        const initialTime = current.currentTime;
        try {
            const result = current.play();
            if (result && result.catch) result.catch(function () {});
        } catch (_) {}
        checkProgress(snapshot, current, initialTime);
    }, 1000);
}

document.addEventListener('visibilitychange', handleVisibilityChange);
window.addEventListener('blur', function () {
    if (document.hidden) return;
    clearRecovery();
    rememberBeforeHide();
});
window.addEventListener('focus', function () {
    setTimeout(handleVisibilityChange, 350);
});
window.addEventListener('pageshow', function () {
    setTimeout(handleVisibilityChange, 350);
});

// Some Tizen quick-resume paths never emit visibilitychange. Poll focus as a
// backup, then detect a suspended JS timer or a player that stopped advancing.
setInterval(function () {
    const now = Date.now();
    const previousTick = lastWatchdogAt;
    const gap = now - previousTick;
    lastWatchdogAt = now;

    const focused = typeof document.hasFocus === 'function' ? document.hasFocus() : null;
    if (focused !== null && lastFocusState !== null && focused !== lastFocusState) {
        lastFocusState = focused;
        if (focused) {
            setTimeout(handleVisibilityChange, 350);
        } else {
            clearRecovery();
            rememberBeforeHide();
        }
    } else if (focused !== null && lastFocusState === null) {
        lastFocusState = focused;
    }

    if (document.hidden || focused === false) return;
    const current = video();
    const id = videoId();
    if (!current || !id || current.ended) return;

    if (lastObservedVideoId !== null && id !== lastObservedVideoId) {
        recoveryAttempted = false;
        lastObservedVideoId = id;
        lastObservedTime = current.currentTime;
        lastConfirmedTime = current.currentTime;
        lastProgressAt = current.paused ? 0 : now;
    }

    // Resume a system-paused video once this page is active again, even when
    // Tizen never fired visibilitychange. A detected user pause stays paused.
    if (backgroundPause && backgroundPause.id === id && intentionalPauseId !== id &&
        !recoveryAttempted && !recoveryTimer && now - backgroundPause.at >= 3000) {
        handleVisibilityChange();
        return;
    }

    // If timers were suspended, recent progress just before the gap is evidence
    // that the app was backgrounded even when Samsung omitted lifecycle events.
    if (gap >= 4000 && !recoveryAttempted && !playbackBeforeHide &&
        hiddenAt === null && now - lastResumeAt >= 8000) {
        const candidate = recentPlayback;
        if (candidate && candidate.id === id && candidate.at >= previousTick - 12000 &&
            intentionalPauseId !== id) {
            playbackBeforeHide = {
                element: current, id: id, time: candidate.time, at: candidate.at
            };
            hiddenAt = previousTick;
            resumeState.stage = 'watchdog-return-detected';
            handleVisibilityChange();
            return;
        }
    }

    // If the page stayed visible but the HTML5 media clock is frozen, recover it
    // without waiting for another app-switch event.
    if (!current.paused && !recoveryTimer && lastProgressAt > 0 &&
        lastObservedVideoId === id && now - lastProgressAt >= 12000) {
        reloadStalledPlayer({ id: id, time: current.currentTime });
    }
}, 2500);

restoreAfterReload();
"""
(ROOT / "mods/features/resumePlayback.js").write_text(resume_playback, encoding="utf-8")

# TizenBrew early-injection hardening, adapted from TizenTube PR #759.
replace_once(
    "mods/spatial-navigation-polyfill.js",
    "    window.Element.prototype.getSpatialNavigationContainer = getSpatialNavigationContainer;\n\n    /*",
    "    window.Element.prototype.getSpatialNavigationContainer = getSpatialNavigationContainer;\n\n    if (!document.documentElement) {\n      document.addEventListener('DOMContentLoaded', initiateSpatialNavigation);\n      return;\n    }\n\n    /*",
    "defer spatial navigation until document root exists"
)

replace_once(
    "mods/ui/theme.js",
    "document.head.appendChild(style);",
    "if (document.head) {\n    document.head.appendChild(style);\n} else {\n    document.addEventListener('DOMContentLoaded', () => document.head.appendChild(style));\n}",
    "defer theme style until document head exists"
)

replace_once(
    "mods/features/pictureInPicture.js",
    "    const mappings = Object.values(window._yttv).find(a => a && a.mappings);\n    PlayerService = mappings.get('PlayerService');\n    const PlaybackPreviewService = mappings.get('PlaybackPreviewService');",
    "    const mappings = Object.values(window._yttv || {}).find(a => a && a.mappings);\n    if (!mappings || typeof mappings.get !== 'function' || !mappings.get('PlayerService') || !mappings.get('PlaybackPreviewService')) {\n        return setTimeout(pipLoad, 250);\n    }\n    PlayerService = mappings.get('PlayerService');\n    const PlaybackPreviewService = mappings.get('PlaybackPreviewService');",
    "wait for TizenTube PiP services"
)

replace_once(
    "mods/features/pictureInPicture.js",
    "observerPipEnter.observe(document.body, { childList: true, subtree: true });",
    "function observePipEnter() {\n    observerPipEnter.observe(document.body, { childList: true, subtree: true });\n}\n\nif (document.body) {\n    observePipEnter();\n} else {\n    document.addEventListener('DOMContentLoaded', observePipEnter);\n}",
    "defer PiP observer until document body exists"
)

replace_once(
    "mods/ui/disableWhosWatching.js",
    "    const LeanbackRecurringActions = JSON.parse(localStorage['yt.leanback.default::recurring_actions']);",
    "    const storedActions = localStorage['yt.leanback.default::recurring_actions'];\n    if (!storedActions) return;\n\n    let LeanbackRecurringActions;\n    try {\n        LeanbackRecurringActions = JSON.parse(storedActions);\n    } catch (e) {\n        console.warn('Unable to read YouTube recurring actions:', e);\n        return;\n    }\n    if (!LeanbackRecurringActions?.data?.data) return;",
    "guard missing or malformed recurring actions"
)
replace_once(
    "mods/ui/disableWhosWatching.js",
    "            LeanbackRecurringActions.data.data.whos_watching_fullscreen_zero_accounts.lastFired = date.getTime();",
    "            LeanbackRecurringActions.data.data.whos_watching_fullscreen_zero_accounts &&\n                (LeanbackRecurringActions.data.data.whos_watching_fullscreen_zero_accounts.lastFired = date.getTime());",
    "guard missing recurring account action (enabled branch)"
)
replace_once(
    "mods/ui/disableWhosWatching.js",
    "        LeanbackRecurringActions.data.data.whos_watching_fullscreen_zero_accounts.lastFired = date.getTime();",
    "        LeanbackRecurringActions.data.data.whos_watching_fullscreen_zero_accounts &&\n            (LeanbackRecurringActions.data.data.whos_watching_fullscreen_zero_accounts.lastFired = date.getTime());",
    "guard missing recurring account action (disabled branch)"
)

replace_once(
    "service/service.js",
    "version: '1.15.4',",
    "version: '1.15.5',",
    "TTCC service version"
)

startup_test = "import assert from 'node:assert/strict';\nimport { readFileSync } from 'node:fs';\nimport { test } from 'node:test';\nimport vm from 'node:vm';\n\nconst bundle = new vm.Script(readFileSync(\n    process.env.TIZENTUBE_TEST_BUNDLE || new URL('../../dist/userScript.js', import.meta.url),\n    'utf8'\n));\nconst actionsKey = 'yt.leanback.default::recurring_actions';\n\nfunction eventTarget() {\n    const listeners = new Map();\n    return {\n        addEventListener(type, listener) {\n            if (!listeners.has(type)) listeners.set(type, []);\n            listeners.get(type).push(listener);\n        },\n        dispatch(type) {\n            for (const listener of listeners.get(type) || []) listener();\n        },\n    };\n}\n\nfunction element() {\n    return {\n        ...eventTarget(),\n        style: {},\n        children: [],\n        classList: { contains: () => false },\n        appendChild(child) { this.children.push(child); },\n        setAttribute() {},\n    };\n}\n\n// Exercise the shipped IIFE with a new JS realm per page. Timers are queued so\n// YouTube's DOM and services can arrive after TizenBrew injects the cached mod.\nfunction page(stage, storedActions, config = {}) {\n    const document = {\n        ...eventTarget(),\n        readyState: stage === 'loaded' ? 'complete' : 'loading',\n        documentElement: stage === 'empty' ? null : element(),\n        head: stage === 'empty' ? null : element(),\n        body: ['empty', 'head'].includes(stage) ? null : element(),\n        createElement: element,\n        querySelector: () => null,\n        getElementById: () => null,\n    };\n    const timers = [];\n    const observations = [];\n    const registeredProperties = [];\n    const storage = { 'ytaf-configuration': JSON.stringify(config) };\n    if (storedActions !== undefined) storage[actionsKey] = storedActions;\n    const context = vm.createContext({\n        ...eventTarget(),\n        document,\n        navigator: { language: 'en-US', userAgent: 'Tizen' },\n        location: { hostname: 'www.youtube.com', href: 'https://www.youtube.com/tv', hash: '' },\n        localStorage: storage,\n        console: { log() {}, info() {}, warn() {}, error() {} },\n        setTimeout(callback) { timers.push(callback); },\n        setInterval() {},\n        clearTimeout() {},\n        clearInterval() {},\n        fetch() {},\n        MutationObserver: class {\n            observe(target) {\n                assert.ok(target, 'MutationObserver needs a DOM node');\n                observations.push(target);\n            }\n        },\n        Element: class {},\n        CSS: { registerProperty(property) { registeredProperties.push(property.name); } },\n        getComputedStyle(target) {\n            assert.ok(target, 'getComputedStyle needs a DOM element');\n            return { getPropertyValue: () => '' };\n        },\n    });\n    vm.runInContext('window = self = globalThis;', context);\n    bundle.runInContext(context);\n    return { context, document, timers, observations, storage, registeredProperties };\n}\n\nfunction assertCoreFeatures(context) {\n    const parsed = vm.runInContext(`JSON.parse('${JSON.stringify({\n        adPlacements: [{}], playerAds: [{}], adSlots: [{}], videoDetails: { videoId: 'test' },\n    })}')`, context);\n    assert.equal(parsed.adPlacements.length, 0);\n    assert.equal(parsed.playerAds, false);\n    assert.equal(parsed.adSlots.length, 0);\n    assert.equal(parsed.videoDetails.videoId, 'test');\n\n    const settings = vm.runInContext('JSON.parse(\\'{\"title\":{\"runs\":[]},\"items\":[]}\\')', context);\n    assert.equal(settings.items.length, 1, 'TizenTube settings are installed');\n    assert.equal(typeof context.ttccChapters, 'function', 'later TTCC chapter diagnostics are installed');\n}\n\nconst validActions = JSON.stringify({\n    data: { data: {\n        'startup-screen-account-selector-with-guest': { lastFired: 0 },\n        whos_watching_fullscreen_zero_accounts: { lastFired: 0 },\n        'startup-screen-signed-out-welcome-back': { lastFired: 0 },\n    } },\n});\n\nfor (const stage of ['empty', 'head', 'body', 'loaded']) {\n    for (const [name, storedActions] of Object.entries({\n        missing: undefined,\n        malformed: 'not JSON',\n        null: 'null',\n        incomplete: '{\"data\":{}}',\n        changed: '{\"data\":{\"data\":{\"new-action\":{\"lastFired\":0}}}}',\n        valid: validActions,\n    })) {\n        test(`startup at ${stage} with ${name} recurring actions keeps ads blocked and settings installed`, () => {\n            const { context, storage } = page(stage, storedActions);\n            assertCoreFeatures(context);\n            if (name === 'valid') {\n                const actions = JSON.parse(storage[actionsKey]).data.data;\n                assert.ok(actions.whos_watching_fullscreen_zero_accounts.lastFired > Date.now());\n            } else {\n                assert.equal(storage[actionsKey], storedActions);\n            }\n        });\n    }\n}\n\ntest('early injection attaches the theme and PiP observer when the DOM arrives', () => {\n    const { context, document, observations, registeredProperties } = page('empty');\n    assert.equal(observations.length, 0);\n    assert.equal(registeredProperties.length, 0);\n    assert.ok(context.__spatialNavigation__, 'navigation APIs are available before the DOM');\n    document.documentElement = element();\n    document.head = element();\n    document.body = element();\n    document.readyState = 'interactive';\n    document.dispatch('DOMContentLoaded');\n    assert.ok(observations.includes(document.body));\n    assert.ok(document.head.children.some(child => child.textContent.includes('#container')));\n    assert.equal(registeredProperties.length, 3, 'navigation CSS registers after the root element exists');\n    context.dispatch('load');\n    assertCoreFeatures(context);\n});\n\ntest('PiP waits for YouTube services when injected into an already loaded page', () => {\n    const { context, timers } = page('loaded');\n    vm.runInContext(`\n        previewCalls = 0;\n        preview = { start() { previewCalls++; }, stop() { previewCalls++; } };\n        services = new Map([['PlayerService', {}], ['PlaybackPreviewService', preview]]);\n        services.mappings = true;\n        _yttv = { services };\n    `, context);\n    for (const callback of timers.splice(0)) callback();\n    vm.runInContext('preview.start(); preview.stop(); isPipPlaying = true; preview.start(); preview.stop();', context);\n    assert.equal(context.previewCalls, 2, 'PiP hooks install after services become available');\n    assertCoreFeatures(context);\n});\n\ntest('enabling the account picker tolerates a missing legacy action', () => {\n    const storedActions = '{\"data\":{\"data\":{\"startup-screen-signed-out-welcome-back\":{\"lastFired\":0}}}}';\n    const { context, storage } = page('body', storedActions, { enableWhoIsWatchingMenu: true });\n    assertCoreFeatures(context);\n    assert.ok(JSON.parse(storage[actionsKey]).data.data['startup-screen-signed-out-welcome-back'].lastFired > 0);\n});\n"
startup_test_path = ROOT / "mods/tests/startup.test.js"
startup_test_path.parent.mkdir(parents=True, exist_ok=True)
startup_test_path.write_text(startup_test, encoding="utf-8")
print("TTCC 1.15.5 launch-compatible patch applied successfully")

