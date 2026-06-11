/**
 * GINI-AI State Manager
 * Manages UI state transitions: idle, listening, thinking, speaking, executing, error
 */

class AssistantStateManager {
    constructor() {
        this.state = 'idle';
        this.previousState = null;
        this.sessionId = null;
        this.userId = 'default';
        this.lastEmotion = null;
        this.lastError = null;
        this.listeners = [];

        this.stateConfig = {
            idle: {
                label: 'Idle',
                color: 'idle',
                inputEnabled: true,
                canSendMessage: true,
                hint: 'Ready to assist',
            },
            listening: {
                label: 'Listening',
                color: 'listening',
                inputEnabled: false,
                canSendMessage: false,
                hint: 'Processing your input...',
            },
            thinking: {
                label: 'Thinking',
                color: 'thinking',
                inputEnabled: false,
                canSendMessage: false,
                hint: 'Analyzing your request...',
            },
            speaking: {
                label: 'Speaking',
                color: 'speaking',
                inputEnabled: false,
                canSendMessage: false,
                hint: 'Generating response...',
            },
            executing: {
                label: 'Executing',
                color: 'executing',
                inputEnabled: false,
                canSendMessage: false,
                hint: 'Executing command...',
            },
            error: {
                label: 'Error',
                color: 'error',
                inputEnabled: true,
                canSendMessage: false,
                hint: 'An error occurred. Try again.',
            },
        };
    }

    /**
     * Transition to a new state
     */
    transition(newState, data = {}) {
        if (!this.stateConfig[newState]) {
            console.error(`Invalid state: ${newState}`);
            return false;
        }

        this.previousState = this.state;
        this.state = newState;

        if (data.sessionId) this.sessionId = data.sessionId;
        if (data.userId) this.userId = data.userId;
        if (data.emotion) this.lastEmotion = data.emotion;
        if (data.error) this.lastError = data.error;

        this.notifyListeners();
        return true;
    }

    /**
     * Pipeline for sending a message
     */
    async processMessage(message) {
        this.transition('listening');
        // Simulate brief listening phase
        await this.delay(200);

        this.transition('thinking');
        return true;
    }

    /**
     * Mark message as processed
     */
    async messageProcessed(response) {
        this.transition('speaking', {
            emotion: response.emotion,
            sessionId: response.session_id,
            userId: response.user_id,
        });

        // Simulate speaking phase
        await this.delay(500);

        this.transition('idle');
    }

    /**
     * Handle error
     */
    handleError(error) {
        this.transition('error', { error: error.message });
    }

    /**
     * Subscribe to state changes
     */
    subscribe(callback) {
        this.listeners.push(callback);
        return () => {
            this.listeners = this.listeners.filter(l => l !== callback);
        };
    }

    /**
     * Notify all listeners of state change
     */
    notifyListeners() {
        this.listeners.forEach(callback => {
            callback({
                state: this.state,
                previousState: this.previousState,
                config: this.stateConfig[this.state],
                sessionId: this.sessionId,
                userId: this.userId,
                emotion: this.lastEmotion,
                error: this.lastError,
            });
        });
    }

    /**
     * Get current state config
     */
    getConfig() {
        return this.stateConfig[this.state];
    }

    /**
     * Get current state info
     */
    getStateInfo() {
        return {
            state: this.state,
            previousState: this.previousState,
            config: this.getConfig(),
            sessionId: this.sessionId,
            userId: this.userId,
            emotion: this.lastEmotion,
            error: this.lastError,
        };
    }

    /**
     * Reset to idle state
     */
    reset() {
        this.transition('idle');
        this.lastEmotion = null;
        this.lastError = null;
    }

    /**
     * Helper: delay
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AssistantStateManager;
}
