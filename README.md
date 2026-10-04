# TTCC

Custom TizenBrew module built from the clean TizenTube 1.15.0 source
(upstream commit 893b663d35efa558d8bdf9f54f0c4f9a31ab6a07).

Changes:
- direct "Turn off screen / Wyłącz ekran" player button;
- safe wake-up: the first non-media remote-key sequence only restores the picture;
- Play/Pause keeps controlling playback while Screen Off stays black, including Samsung trailing key events;
- blackout uses an html pseudo-element so resuming playback cannot remove it during a YouTube UI rerender;
- no global display:block restore, preventing Theme Configuration from appearing on wake;
- DIAL/casting launches gh/p4veu/ttcc rather than the upstream npm module.
- TEST: POST /ttcc/search on local port 8096 to show HA voice search results.
- Visibility diagnostics: /ttcc/status reports hidden, focused and visibilityState from the TV page.
- TEST: POST /ttcc/screen supports voice screen on/off via the same HA bridge.
- TEST: POST /ttcc/search accepts auto_screen_off=true to darken after a selected film starts playing.
- TEST: POST /ttcc/playlist opens a playlist by playlist_id and attempts to start playback.
- TEST: Chapter markers and the selected chapter name appear on the playback bar; one fallback metadata request per video.
- Chapter overlay stays outside YouTube's frequently rebuilt progress-bar DOM.
- Previous confirmed-working version .5 is preserved on stable-fully-working-ttcc-1.15.0-ttcc.5 branch.

Upstream: https://github.com/reisxd/TizenTube
License: GPL-3.0-only
