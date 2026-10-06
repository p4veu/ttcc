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

# Build from the clean upstream TizenTube 1.15.0 source and change only:
# 1) direct Screen Off button placement,
# 2) Screen Off wake-up behavior,
# 3) DIAL/casting target.

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

                    if (!res.find(item => item.type === 'TRANSPORT_CONTROLS_BUTTON_TYPE_TURN_OFF_SCREEN')) {
                        // Keep YouTube's native first engagement action in place.
                        // On this TV putting Screen Off first can break RIGHT navigation
                        // from the main player controls into the engagement-action row.
                        res.push(screenOffCommand);
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

// Minimal read-only health check: usable from any phone on the LAN.
app.get('/ttcc/status', (req, res) => {
    res.json({
        ok: true,
        version: '1.15.0-ttcc.13-focus-nav',
        connected: haLastPoll > 0 && (Date.now() - haLastPoll) < 7000,
        hidden: haHidden,
        focused: haFocused,
        visibilityState: haVisibilityState,
        screenOff: haScreenOff,
        autoScreenOffArmed: haAutoScreenOffArmed,
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
    const flags = '&hidden=' + (document.hidden ? '1' : '0') +
                  '&focus=' + focus + '&visibility=' + visibility +
                  '&black=' + (document.documentElement.getAttribute('data-ttcc-screen-off') === '1' ? '1' : '0') +
                  '&armed=' + (autoScreenOffArmed ? '1' : '0');
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
entry_text += "\nimport './features/haSearch.js';\n"
entry.write_text(entry_text, encoding="utf-8")

print("TTCC 1.15.0-ttcc.13-focus-nav patch applied successfully")
