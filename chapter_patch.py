"""Add the TTCC chapter feature to the pinned, already patched TizenTube tree."""
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('upstream')


def replace_once(path, old, new):
    target = root / path
    source = target.read_text(encoding='utf-8')
    if source.count(old) != 1:
        raise SystemExit(f'{path}: expected one marker, found {source.count(old)}')
    target.write_text(source.replace(old, new, 1), encoding='utf-8')


(root / 'mods/features/ttccChapters.js').write_text(
    Path(__file__).with_name('ttcc_chapters.js').read_text(encoding='utf-8'),
    encoding='utf-8')

replace_once('mods/features/adblock.js',
             "import Chapters from '../ui/chapters.js';",
             "import Chapters from '../ui/chapters.js';\nimport { observeChapterResponse } from './ttccChapters.js';")
replace_once('mods/features/adblock.js',
             '  const r = origParse.apply(this, arguments);\n  try {',
             '  const r = origParse.apply(this, arguments);\n  try {\n    observeChapterResponse(r);')
replace_once('mods/userScript.js',
             "import './features/haSearch.js';",
             "import './features/haSearch.js';\nimport './features/ttccChapters.js';")

# The existing LAN status endpoint lets us verify the result on the TV without
# enabling remote developer tools or recording private YouTube data.
replace_once('service/service.js',
             'let haAutoScreenOffArmed = null;',
             'let haAutoScreenOffArmed = null;\nlet haChapterCount = 0;')
replace_once('service/service.js',
             "version: '1.15.0-ttcc.9-playlists',",
             "version: '1.15.0-ttcc.11-chapters-ui',")
replace_once('service/service.js',
             'autoScreenOffArmed: haAutoScreenOffArmed,\n        pending:',
             'autoScreenOffArmed: haAutoScreenOffArmed,\n        chapterCount: haChapterCount,\n        pending:')
replace_once('service/service.js',
             "haAutoScreenOffArmed = req.query.armed === '1' ? true : req.query.armed === '0' ? false : null;",
             "haAutoScreenOffArmed = req.query.armed === '1' ? true : req.query.armed === '0' ? false : null;\n    haChapterCount = Math.max(0, Math.min(200, Number(req.query.chapters) || 0));")
replace_once('mods/features/haSearch.js',
             "'&armed=' + (autoScreenOffArmed ? '1' : '0');",
             "'&armed=' + (autoScreenOffArmed ? '1' : '0') +\n                  '&chapters=' + (window.ttccChapters ? window.ttccChapters().count : 0);")

print('TTCC chapter patch applied')
