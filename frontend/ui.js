/**
 * GINI-AI UI Manager
 * Handles DOM updates based on state changes
 */

class AssistantUIManager {
    constructor() {
        this.elements = {
            statusDot: document.getElementById('status-dot'),
            statusText: document.getElementById('status-text'),
            currentState: document.getElementById('current-state'),
            lastEmotion: document.getElementById('last-emotion'),
            errorDisplay: document.getElementById('error-display'),
            messageInput: document.getElementById('message-input'),
            sendButton: document.getElementById('send-button'),
            chatMessages: document.getElementById('chat-messages'),
            inputHint: document.getElementById('input-hint'),
            assistantStatus: document.getElementById('assistant-status'),
            sessionId: document.getElementById('session-id'),
            userId: document.getElementById('user-id'),
        };

        this.emotionEmojis = {
            positive: '😊',
            negative: '😞',
            neutral: '😐',
        };
    }

    /**
     * Update UI based on state change
     */
    updateState(stateInfo) {
        const { state, config, emotion, error } = stateInfo;

        // Update status indicator
        this.elements.statusDot.className = `status-dot ${config.color}`;
        this.elements.statusText.textContent = config.label;

        // Update current state display
        this.elements.currentState.textContent = state;

        // Update emotion display
        if (emotion) {
            const emoji = this.emotionEmojis[emotion] || '?';
            this.elements.lastEmotion.textContent = `${emoji} ${emotion}`;
        }

        // Update input controls
        this.elements.messageInput.disabled = !config.inputEnabled;
        this.elements.sendButton.disabled = !config.canSendMessage;

        // Update hint
        this.elements.inputHint.textContent = config.hint;

        // Handle error display
        if (error) {
            this.showError(error);
        } else {
            this.hideError();
        }
    }

    /**
     * Add a message to chat
     */
    addMessage(content, role = 'user') {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;

        const p = document.createElement('p');
        p.textContent = content;

        messageDiv.appendChild(p);
        this.elements.chatMessages.appendChild(messageDiv);
        this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
    }

    /**
     * Update session info
     */
    updateSessionInfo(userId, sessionId) {
        this.elements.userId.textContent = userId || 'default';
        this.elements.sessionId.textContent = sessionId || '—';
    }

    /**
     * Update assistant status
     */
    updateAssistantStatus(isRunning) {
        const status = isRunning ? '✅ Running' : '❌ Offline';
        const className = isRunning ? 'online' : 'offline';
        this.elements.assistantStatus.textContent = status;
        this.elements.assistantStatus.className = className;
    }

    /**
     * Show error message
     */
    showError(errorMessage) {
        this.elements.errorDisplay.textContent = `❌ ${errorMessage}`;
        this.elements.errorDisplay.style.display = 'block';
    }

    /**
     * Hide error message
     */
    hideError() {
        this.elements.errorDisplay.style.display = 'none';
        this.elements.errorDisplay.textContent = '';
    }

    /**
     * Clear chat
     */
    clearChat() {
        this.elements.chatMessages.innerHTML = '';
    }

    /**
     * Get input value and clear
     */
    getInputAndClear() {
        const value = this.elements.messageInput.value.trim();
        this.elements.messageInput.value = '';
        return value;
    }

    /**
     * Focus input
     */
    focusInput() {
        this.elements.messageInput.focus();
    }

    /**
     * Show loading spinner in chat
     */
    showLoadingIndicator() {
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'message system loading';
        loadingDiv.id = 'loading-indicator';
        loadingDiv.innerHTML = '<p>Thinking<span class="dots"></span></p>';
        this.elements.chatMessages.appendChild(loadingDiv);
        this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
    }

    /**
     * Remove loading spinner
     */
    removeLoadingIndicator() {
        const loading = document.getElementById('loading-indicator');
        if (loading) loading.remove();
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AssistantUIManager;
}
