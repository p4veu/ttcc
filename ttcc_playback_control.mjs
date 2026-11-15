const PAUSE_LABEL = /\b(?:pause|wstrzymaj|pauza|pauzuj)\b/i;
const PLAY_LABEL = /\b(?:play|odtwórz|odtworz)\b/i;

function labelOf(element) {
    if (!element) return '';
    return [
        element.getAttribute && element.getAttribute('aria-label'),
        element.getAttribute && element.getAttribute('title'),
        element.className,
        element.textContent
    ].filter(Boolean).join(' ');
}

function pauseIntentFromLabel(label, currentlyPlaying) {
    const hasPause = PAUSE_LABEL.test(label);
    const hasPlay = PLAY_LABEL.test(label);
    if (hasPause && !hasPlay) return currentlyPlaying;
    if (hasPlay && !hasPause) return false;
    // Combined labels such as "Play/Pause" are toggle controls.
    return hasPause && hasPlay && currentlyPlaying;
}

/**
 * Distinguish a user's pause/stop action from a Play command.
 * Samsung TVs can emit a pause event shortly after a Play key when the media
 * pipeline is still waking up. That pause must be recoverable, not classified
 * as an intentional user pause.
 */
export function isUserStopOrPauseControl(event, currentVideo, activeElement) {
    if (!event || typeof event.type !== 'string') return false;
    const currentlyPlaying = Boolean(currentVideo && !currentVideo.paused && !currentVideo.ended);

    if (event.type === 'keydown') {
        const code = event.keyCode || event.which || 0;
        const key = event.key || '';

        // A Play key is never evidence that the user intended to pause.
        if (key === 'MediaPlay' || code === 415) return false;
        // Explicit Pause and Stop keys should preserve the user's choice.
        if (key === 'MediaPause' || code === 19 || key === 'MediaStop' || code === 413) {
            return currentlyPlaying;
        }
        // Toggle keys count as a pause only when playback was active beforehand.
        if (key === 'MediaPlayPause' || code === 10252 || code === 32 || key === ' ') {
            return currentlyPlaying;
        }
        if (code === 13 || key === 'Enter') {
            return pauseIntentFromLabel(labelOf(activeElement || event.target), currentlyPlaying);
        }
        return false;
    }

    const target = event.target && typeof event.target.closest === 'function'
        ? event.target.closest('video,button,[role="button"]')
        : event.target;
    if (!target) return false;
    if (target.tagName && target.tagName.toLowerCase() === 'video') return currentlyPlaying;
    return pauseIntentFromLabel(labelOf(target), currentlyPlaying);
}
