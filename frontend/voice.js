/**
 * GINI-AI Voice Manager v2
 * voice.js
 *
 * Full voice pipeline for browser:
 *   Mic Press → Listen → Speech Recognition → Auto-submit
 *   → Response → Text-To-Speech (female voice) → Idle
 *
 * States: idle | listening | processing | speaking | error
 * Handles: no mic, permission denied, silence, network error, TTS failure
 */

'use strict';

class GiniVoiceManager {
    /**
     * @param {Object} callbacks
     *   onTranscript(text)       — final recognised text, triggers auto-submit
     *   onInterim(text)          — live partial text (shown in input field)
     *   onStateChange(state)     — state machine transitions
     *   onSpeakStart()           — TTS started
     *   onSpeakEnd()             — TTS finished
     *   onError(message)         — human-readable error string
     */
    constructor({
        onTranscript  = null,
        onInterim     = null,
        onStateChange = null,
        onSpeakStart  = null,
        onSpeakEnd    = null,
        onError       = null,
    } = {}) {
        this._cb = { onTranscript, onInterim, onStateChange, onSpeakStart, onSpeakEnd, onError };

        // State machine
        this._state = 'idle';

        // Browser STT
        this._recognition = null;
        this._recognitionActive = false;

        // Browser TTS
        this._synth = window.speechSynthesis || null;
        this._femaleVoice = null;
        this._currentUtterance = null;

        // Voice loop (auto-listen after speaking)
        this._voiceLoop = false;

        // Init
        this._initRecognition();
        this._initTTS();
    }

    // ─── Initialisation ───────────────────────────────────────

    _initRecognition() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            console.warn('[Gini Voice] SpeechRecognition not supported in this browser.');
            return;
        }

        const rec = new SR();
        rec.continuous      = false;
        rec.interimResults  = true;
        rec.lang            = 'en-IN';
        rec.maxAlternatives = 1;

        rec.onstart = () => {
            this._recognitionActive = true;
            this._setState('listening');
        };

        rec.onresult = (event) => {
            let interim = '';
            let final   = '';

            for (let i = event.resultIndex; i < event.results.length; i++) {
                const t = event.results[i][0].transcript;
                if (event.results[i].isFinal) final   += t;
                else                           interim += t;
            }

            // Live preview
            if (interim) this._cb.onInterim?.(interim);

            // Final → auto-submit
            if (final.trim()) {
                this._cb.onInterim?.(final.trim());
                this._setState('processing');
                this._cb.onTranscript?.(final.trim());
            }
        };

        rec.onerror = (event) => {
            this._recognitionActive = false;
            this._handleRecognitionError(event.error);
        };

        rec.onend = () => {
            this._recognitionActive = false;
            // If we ended while still 'listening' → silence / no speech
            if (this._state === 'listening') {
                this._handleRecognitionError('no-speech');
            }
        };

        this._recognition = rec;
    }

    _initTTS() {
        if (!this._synth) {
            console.warn('[Gini Voice] SpeechSynthesis not supported.');
            return;
        }

        // Voices may load asynchronously
        this._loadVoices();
        if (typeof this._synth.onvoiceschanged !== 'undefined') {
            this._synth.onvoiceschanged = () => this._loadVoices();
        }
    }

    _loadVoices() {
        const voices = this._synth.getVoices();
        if (!voices.length) return;

        /*
         * Priority order for female voice selection:
         * 1. Indian English female
         * 2. British English female
         * 3. US English female
         * 4. Any English female
         * 5. Named female voices (Raveena, Zira, Samantha, Hazel…)
         * 6. Any Indian English
         * 7. Any British English
         * 8. Any English
         */
        const FEMALE_NAMES = /raveena|zira|samantha|victoria|hazel|heera|microsoft zira|google uk english female|karen|moira|fiona|veena/i;
        const FEMALE_LABEL = /female|woman|girl/i;

        const matchers = [
            v => v.lang === 'en-IN'  && (FEMALE_LABEL.test(v.name) || FEMALE_NAMES.test(v.name)),
            v => v.lang === 'en-GB'  && (FEMALE_LABEL.test(v.name) || FEMALE_NAMES.test(v.name)),
            v => v.lang === 'en-US'  && (FEMALE_LABEL.test(v.name) || FEMALE_NAMES.test(v.name)),
            v => v.lang.startsWith('en') && (FEMALE_LABEL.test(v.name) || FEMALE_NAMES.test(v.name)),
            v => FEMALE_NAMES.test(v.name),
            v => v.lang === 'en-IN',
            v => v.lang === 'en-GB',
            v => v.lang === 'en-US',
            v => v.lang.startsWith('en'),
        ];

        for (const match of matchers) {
            const found = voices.find(match);
            if (found) {
                this._femaleVoice = found;
                console.log(`[Gini Voice] TTS voice: "${found.name}" (${found.lang})`);
                break;
            }
        }
    }

    // ─── Public API ───────────────────────────────────────────

    /**
     * Start listening. Ignored if already in active state.
     * Stops any current TTS playback first.
     */
    startListening() {
        if (!this._recognition) {
            this._cb.onError?.('Speech recognition is not supported in this browser. Please use Chrome or Edge.');
            return;
        }
        if (this._state !== 'idle' && this._state !== 'error') return;

        // Cancel any speaking
        this._synth?.cancel();
        this._currentUtterance = null;

        try {
            this._setState('listening');
            this._recognition.start();
        } catch (e) {
            // InvalidStateError = already started (race condition)
            if (e.name === 'InvalidStateError') return;
            this._handleRecognitionError('start-failed');
        }
    }

    /**
     * Abort current listening session silently.
     */
    stopListening() {
        if (this._recognition && this._recognitionActive) {
            try { this._recognition.abort(); } catch (_) {}
        }
        if (this._state === 'listening') {
            this._setState('idle');
        }
    }

    /**
     * Speak text using the browser's TTS with the selected female voice.
     * @param {string}   text
     * @param {Function} [onComplete]  — called when speech ends or is skipped
     */
    speak(text, onComplete = null) {
        if (!this._synth) {
            console.warn('[Gini Voice] TTS not available.');
            onComplete?.();
            this._setState('idle');
            return;
        }

        if (!text || !text.trim()) {
            onComplete?.();
            this._setState('idle');
            return;
        }

        // Stop any in-progress TTS
        this._synth.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.voice  = this._femaleVoice;
        utterance.rate   = 0.92;    // Slightly slower — natural pacing
        utterance.pitch  = 1.1;     // Slightly higher — feminine
        utterance.volume = 1.0;
        utterance.lang   = this._femaleVoice?.lang || 'en-IN';

        utterance.onstart = () => {
            this._setState('speaking');
            this._cb.onSpeakStart?.();
        };

        utterance.onend = () => {
            this._currentUtterance = null;
            this._setState('idle');
            this._cb.onSpeakEnd?.();
            onComplete?.();

            // Voice loop: auto-restart listening after speaking
            if (this._voiceLoop) {
                setTimeout(() => this.startListening(), 300);
            }
        };

        utterance.onerror = (e) => {
            this._currentUtterance = null;
            // 'interrupted' is normal (user pressed mic to stop)
            if (e.error !== 'interrupted' && e.error !== 'canceled') {
                console.warn('[Gini Voice] TTS error:', e.error);
            }
            this._setState('idle');
            this._cb.onSpeakEnd?.();
            onComplete?.();
        };

        this._currentUtterance = utterance;
        this._synth.speak(utterance);

        // Chrome bug: sometimes TTS pauses if tab loses focus — resume it
        this._chromeTTSWatchdog(utterance);
    }

    /**
     * Stop ongoing TTS and go back to idle.
     */
    stopSpeaking() {
        this._synth?.cancel();
        this._currentUtterance = null;
        this._setState('idle');
    }

    /**
     * Enable / disable automatic re-listen after each spoken response.
     * @param {boolean} enabled
     */
    setVoiceLoop(enabled) {
        this._voiceLoop = enabled;
        console.log(`[Gini Voice] Voice loop: ${enabled ? 'ON' : 'OFF'}`);
    }

    get voiceLoopEnabled() {
        return this._voiceLoop;
    }

    get state() {
        return this._state;
    }

    /** True if SpeechRecognition is available in this browser */
    static isSupported() {
        return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    }

    /** True if SpeechSynthesis is available in this browser */
    static isTTSSupported() {
        return !!window.speechSynthesis;
    }

    // ─── Internal helpers ─────────────────────────────────────

    _setState(newState) {
        if (this._state === newState) return;
        const prev = this._state;
        this._state = newState;
        console.log(`[Gini Voice] ${prev} → ${newState}`);
        this._cb.onStateChange?.(newState, prev);
    }

    _handleRecognitionError(errorCode) {
        const messages = {
            'no-speech'          : 'No speech detected. Tap 🎤 to try again.',
            'audio-capture'      : 'Microphone not accessible. Check your microphone.',
            'not-allowed'        : 'Microphone permission denied. Please allow microphone access in your browser.',
            'network'            : 'Network error. Check your internet connection.',
            'aborted'            : null,  // Intentional abort — stay silent
            'service-not-allowed': 'Speech service blocked. Try using HTTPS.',
            'bad-grammar'        : 'Could not understand speech. Please try again.',
            'language-not-supported': 'Language not supported. Using English.',
            'start-failed'       : 'Could not start microphone. Please try again.',
        };

        // Silent recovery for user-triggered aborts
        if (errorCode === 'aborted') {
            if (this._state === 'listening') this._setState('idle');
            return;
        }

        const msg = messages[errorCode] || `Voice error: ${errorCode}. Please try again.`;
        this._setState('error');
        this._cb.onError?.(msg);

        // Auto-recover to idle after 4 seconds
        setTimeout(() => {
            if (this._state === 'error') this._setState('idle');
        }, 4000);
    }

    /**
     * Chrome has a bug where SpeechSynthesis pauses when the page is backgrounded.
     * This watchdog resumes it every second while speaking.
     */
    _chromeTTSWatchdog(utterance) {
        if (!this._synth) return;
        const interval = setInterval(() => {
            if (!this._synth.speaking || this._currentUtterance !== utterance) {
                clearInterval(interval);
                return;
            }
            if (this._synth.paused) {
                this._synth.resume();
            }
        }, 1000);
    }
}

// Export for non-module environments
if (typeof module !== 'undefined' && module.exports) {
    module.exports = GiniVoiceManager;
}
