/**
 * GINI-AI Main Application v2
 * app.js
 *
 * Integrates: API client, State manager, UI manager, Voice manager.
 * Voice flow: Mic Press → Listen → Recognize → Auto-submit → Response → TTS → Idle
 */

'use strict';

class GiniAssistantApp {
    constructor() {
        this.api          = new GiniAPIClient('https://gini-ag1b.onrender.com');
        this.stateManager = new AssistantStateManager();
        this.ui           = new AssistantUIManager();
        this.voiceManager = null;  // Initialised in initVoice()

        this._lastResponseText = '';   // Used by voice auto-speak

        this.init();
    }

    // ─── Boot ─────────────────────────────────────────────────

    async init() {
        console.log('🚀 Initialising GINI-AI Assistant...');

        // Wire state → UI
        this.stateManager.subscribe(stateInfo => {
            this.ui.updateState(stateInfo);
        });

        // DOM listeners (text chat)
        this._setupEventListeners();

        // Voice
        this._initVoice();

        // Health check
        await this._checkBackendHealth();

        // Ready
        this.stateManager.transition('idle');
        console.log('✅ GINI-AI ready');
    }

    // ─── Text chat event listeners ────────────────────────────

    _setupEventListeners() {
        const input   = this.ui.elements.messageInput;
        const sendBtn = this.ui.elements.sendButton;

        // Send button
        sendBtn.addEventListener('click', () => this.handleSendMessage());

        // Enter key
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !sendBtn.disabled) {
                this.handleSendMessage();
            }
        });

        // Quick-action chips
        document.querySelectorAll('.action-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const command = btn.dataset.command;
                input.value = command;
                if (!sendBtn.disabled) this.handleSendMessage();
                else this.ui.focusInput();
            });
        });
    }

    // ─── Voice initialisation ─────────────────────────────────

    _initVoice() {
        const micBtn       = document.getElementById('micBtn');
        const loopToggle   = document.getElementById('voiceLoopToggle');
        const voiceStatus  = document.getElementById('voiceStatus');

        // Remove the old inline onclick so we control it here
        if (micBtn) micBtn.removeAttribute('onclick');

        if (!GiniVoiceManager.isSupported()) {
            console.warn('[Voice] SpeechRecognition not supported — mic disabled.');
            if (micBtn) {
                micBtn.disabled = true;
                micBtn.title    = 'Voice not supported. Use Chrome or Edge.';
                micBtn.classList.add('voice-unsupported');
            }
            return;
        }

        // Create voice manager with all callbacks wired
        this.voiceManager = new GiniVoiceManager({

            // Final transcript → auto-submit
            onTranscript: (text) => {
                this._handleVoiceTranscript(text);
            },

            // Interim (live) → show in input field
            onInterim: (text) => {
                const input = this.ui.elements.messageInput;
                input.value = text;
                input.classList.add('voice-interim');
            },

            // State transitions → update mic button + status label
            onStateChange: (state) => {
                this._updateMicUI(state);
            },

            // TTS started → update state manager
            onSpeakStart: () => {
                this.stateManager.transition('speaking');
                if (voiceStatus) voiceStatus.textContent = '🔊 Speaking...';
            },

            // TTS finished → return to idle
            onSpeakEnd: () => {
                this.stateManager.transition('idle');
                if (voiceStatus) voiceStatus.textContent = '';
            },

            // Errors → show in UI, never crash
            onError: (message) => {
                console.warn('[Voice Error]', message);
                this.stateManager.transition('error', { error: message });
                this.ui.showError(message);
                // Auto-clear after 5 s
                setTimeout(() => {
                    if (this.stateManager.state === 'error') {
                        this.stateManager.transition('idle');
                        this.ui.hideError();
                    }
                }, 5000);
            },
        });

        // Mic button: tap to toggle listen / stop
        if (micBtn) {
            micBtn.addEventListener('click', () => this._handleMicClick());
            this._updateMicUI('idle');
        }

        // Voice loop toggle
        if (loopToggle) {
            loopToggle.addEventListener('click', () => {
                const enabled = !this.voiceManager.voiceLoopEnabled;
                this.voiceManager.setVoiceLoop(enabled);
                loopToggle.classList.toggle('active', enabled);
                loopToggle.title = enabled
                    ? 'Voice loop ON — Gini will keep listening after responding'
                    : 'Voice loop OFF';
            });
        }
    }

    // ─── Mic button click handler ─────────────────────────────

    _handleMicClick() {
        if (!this.voiceManager) return;

        const state = this.voiceManager.state;

        if (state === 'listening') {
            // Second tap → cancel
            this.voiceManager.stopListening();
        } else if (state === 'speaking') {
            // Tap while speaking → interrupt and listen
            this.voiceManager.stopSpeaking();
            setTimeout(() => this.voiceManager.startListening(), 150);
        } else if (state === 'idle' || state === 'error') {
            // Normal tap → start
            this.ui.elements.messageInput.classList.remove('voice-interim');
            this.ui.elements.messageInput.value = '';
            this.voiceManager.startListening();
        }
        // 'processing' state → ignore taps (wait for auto-submit)
    }

    // ─── Update mic button based on voice state ────────────────

    _updateMicUI(state) {
        const micBtn      = document.getElementById('micBtn');
        const voiceStatus = document.getElementById('voiceStatus');
        if (!micBtn) return;

        // Remove all state classes then add current
        micBtn.classList.remove('voice-idle', 'voice-listening', 'voice-processing', 'voice-speaking', 'voice-error');
        micBtn.classList.add(`voice-${state}`);

        const labels = {
            idle:       { icon: '🎤', tip: 'Start voice input' },
            listening:  { icon: '🔴', tip: 'Listening… tap to cancel' },
            processing: { icon: '⏳', tip: 'Processing speech…' },
            speaking:   { icon: '🔊', tip: 'Speaking… tap to interrupt' },
            error:      { icon: '⚠️', tip: 'Voice error — tap to retry' },
        };

        const label = labels[state] || labels.idle;
        micBtn.textContent = label.icon;
        micBtn.title       = label.tip;

        const statusTexts = {
            listening:  '🎤 Listening…',
            processing: '⏳ Processing…',
            speaking:   '🔊 Speaking…',
            error:      '⚠️ Voice error',
            idle:       '',
        };
        if (voiceStatus) voiceStatus.textContent = statusTexts[state] ?? '';
    }

    // ─── Voice transcript → auto-submit ───────────────────────

    async _handleVoiceTranscript(transcript) {
        // Clear interim styling
        const input = this.ui.elements.messageInput;
        input.classList.remove('voice-interim');
        input.value = transcript;

        // Auto-submit — same as pressing Send
        await this.handleSendMessage(true);
    }

    // ─── Core message handler ─────────────────────────────────

    /**
     * Send a message to the backend and display the response.
     * @param {boolean} fromVoice — if true, auto-speaks the response
     */
    async handleSendMessage(fromVoice = false) {
        const message = this.ui.getInputAndClear();
        if (!message || !message.trim()) return;

        try {
            // Show user bubble
            this.ui.addMessage(message, 'user');

            // State: listening → thinking
            await this.stateManager.processMessage(message);

            // Loading indicator
            this.ui.showLoadingIndicator();

            // API call
            const response = await this.api.sendMessage(
                message,
                this.stateManager.userId,
                this.stateManager.sessionId,
            );

            // Remove spinner
            this.ui.removeLoadingIndicator();

            // Show assistant response bubble
            this.ui.addMessage(response.response, 'assistant');

            // Update session
            this.stateManager.sessionId = response.session_id;
            this.ui.updateSessionInfo(response.user_id, response.session_id);

            this._lastResponseText = response.response || '';

            // ── Voice: auto-speak response ──────────────────
            if (fromVoice && this.voiceManager) {
                // Skip the simulated speaking delay in stateManager — voice manager owns that state
                this.stateManager.transition('idle');
                this.voiceManager.speak(response.response);
            } else {
                // Text-only flow: brief simulated speaking state then idle
                await this.stateManager.messageProcessed(response);
            }

        } catch (error) {
            this.ui.removeLoadingIndicator();
            console.error('Error sending message:', error);
            this.stateManager.handleError(error);
            this.ui.addMessage(`⚠️ Error: ${error.message}`, 'system');

            // Voice: recover to idle on error
            if (fromVoice && this.voiceManager) {
                setTimeout(() => {
                    if (this.stateManager.state === 'error') {
                        this.stateManager.transition('idle');
                    }
                }, 3000);
            }
        }
    }

    // ─── Action execution (unchanged) ─────────────────────────

    async executeAction(intent, payload = {}) {
        try {
            this.stateManager.transition('executing');
            const result = await this.api.executeAction(intent, payload);
            this.ui.addMessage(`Action executed: ${JSON.stringify(result)}`, 'system');
            this.stateManager.transition('idle');
            return result;
        } catch (error) {
            this.stateManager.handleError(error);
            this.ui.addMessage(`⚠️ Action failed: ${error.message}`, 'system');
        }
    }

    // ─── Health check ─────────────────────────────────────────

    async _checkBackendHealth() {
        try {
            const health = await this.api.getHealth();
            if (health && health.status) {
                this.ui.updateAssistantStatus(health.status === 'healthy');
                console.log('✅ Backend healthy');
            }
        } catch (error) {
            console.error('❌ Backend health check failed:', error);
            this.ui.updateAssistantStatus(false);
            this.ui.showError('Backend is not responding. Check connection.');
        }
    }
}

// ── Boot ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.app = new GiniAssistantApp();
});
