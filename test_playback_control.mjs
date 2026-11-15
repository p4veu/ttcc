import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isUserStopOrPauseControl } from './ttcc_playback_control.mjs';

const playing = { paused: false, ended: false };
const paused = { paused: true, ended: false };
const key = (key, keyCode) => ({ type: 'keydown', key, keyCode, which: keyCode });
const element = (tagName, label) => ({
    tagName,
    textContent: '',
    className: '',
    getAttribute(name) { return name === 'aria-label' ? label : null; },
    closest() { return this; }
});

test('MediaPlay is not mistaken for an intentional pause', () => {
    assert.equal(isUserStopOrPauseControl(key('MediaPlay', 415), paused, null), false);
    assert.equal(isUserStopOrPauseControl(key('MediaPlay', 415), playing, null), false);
});

test('MediaPause and MediaStop preserve an explicit user stop/pause', () => {
    assert.equal(isUserStopOrPauseControl(key('MediaPause', 19), playing, null), true);
    assert.equal(isUserStopOrPauseControl(key('MediaStop', 413), playing, null), true);
    assert.equal(isUserStopOrPauseControl(key('MediaPause', 19), paused, null), false);
});

test('Play/Pause toggle is interpreted using the state before the key event', () => {
    assert.equal(isUserStopOrPauseControl(key('MediaPlayPause', 10252), playing, null), true);
    assert.equal(isUserStopOrPauseControl(key('MediaPlayPause', 10252), paused, null), false);
});

test('Enter on a Play button does not suppress recovery', () => {
    assert.equal(isUserStopOrPauseControl(key('Enter', 13), paused,
        element('BUTTON', 'Play')), false);
});

test('Enter on a Pause button is treated as intentional', () => {
    assert.equal(isUserStopOrPauseControl(key('Enter', 13), playing,
        element('BUTTON', 'Pause')), true);
});

test('video click is a pause only when it starts from active playback', () => {
    assert.equal(isUserStopOrPauseControl({ type: 'click', target: element('VIDEO', '') }, paused, null), false);
    assert.equal(isUserStopOrPauseControl({ type: 'click', target: element('VIDEO', '') }, playing, null), true);
});

test('Polish playback labels distinguish Play from Pause', () => {
    assert.equal(isUserStopOrPauseControl({ type: 'click', target: element('BUTTON', 'Odtwórz') }, paused, null), false);
    assert.equal(isUserStopOrPauseControl({ type: 'click', target: element('BUTTON', 'Wstrzymaj') }, playing, null), true);
});

test('combined Play/Pause button follows the current playback state', () => {
    assert.equal(isUserStopOrPauseControl({ type: 'click', target: element('BUTTON', 'Play/Pause') }, paused, null), false);
    assert.equal(isUserStopOrPauseControl({ type: 'click', target: element('BUTTON', 'Play/Pause') }, playing, null), true);
});
