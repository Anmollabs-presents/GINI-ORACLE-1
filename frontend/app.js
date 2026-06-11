/**
 * GINI-AI Main Application
 * Integrates API, State, and UI managers
 */

class GiniAssistantApp {
    constructor() {
        this.api = new GiniAPIClient('localhost:8000');
        this.stateManager = new AssistantStateManager();
        this.ui = new AssistantUIManager();

        this.init();
    }

    /**
     * Initialize application
     */
    async init() {
        console.log('🚀 Initializing GINI-AI Assistant...');

        // Setup event listeners
        this.setupEventListeners();

        // Subscribe to state changes
        this.stateManager.subscribe(stateInfo => {
            this.ui.updateState(stateInfo);
        });

        // Check backend health
        await this.checkBackendHealth();

        // Enable initial state
        this.stateManager.transition('idle');
    }

    /**
     * Setup DOM event listeners
     */
    setupEventListeners() {
        const input = this.ui.elements.messageInput;
        const sendBtn = this.ui.elements.sendButton;

        // Send button click
        sendBtn.addEventListener('click', () => this.handleSendMessage());

        // Enter key in input
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !sendBtn.disabled) {
                this.handleSendMessage();
            }
        });

        // Quick action buttons
        document.querySelectorAll('.action-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const command = btn.dataset.command;
                this.ui.elements.messageInput.value = command;
                this.ui.focusInput();
                if (!sendBtn.disabled) {
                    this.handleSendMessage();
                }
            });
        });
    }

    /**
     * Check backend health on startup
     */
    async checkBackendHealth() {
        try {
            const health = await this.api.getHealth();
            if (health && health.status) {
                this.ui.updateAssistantStatus(health.status === 'healthy');
                console.log('✅ Backend is healthy');
            }
        } catch (error) {
            console.error('❌ Backend health check failed:', error);
            this.ui.updateAssistantStatus(false);
            this.ui.showError('Backend is not responding. Please check connection.');
        }
    }

    /**
     * Handle sending a message
     */
    async handleSendMessage() {
        const message = this.ui.getInputAndClear();
        if (!message) return;

        try {
            // Add user message to chat
            this.ui.addMessage(message, 'user');

            // Update state to processing
            await this.stateManager.processMessage(message);

            // Show loading
            this.ui.showLoadingIndicator();

            // Send to backend
            const response = await this.api.sendMessage(
                message,
                this.stateManager.userId,
                this.stateManager.sessionId
            );

            // Remove loading
            this.ui.removeLoadingIndicator();

            // Add assistant response to chat
            this.ui.addMessage(response.response, 'assistant');

            // Update session and state
            this.stateManager.sessionId = response.session_id;
            this.ui.updateSessionInfo(response.user_id, response.session_id);

            // Mark as processed
            await this.stateManager.messageProcessed(response);

        } catch (error) {
            this.ui.removeLoadingIndicator();
            console.error('Error sending message:', error);
            this.stateManager.handleError(error);
            this.ui.addMessage(`Error: ${error.message}`, 'system');
        }
    }

    /**
     * Execute a quick action
     */
    async executeAction(intent, payload = {}) {
        try {
            this.stateManager.transition('executing');
            const result = await this.api.executeAction(intent, payload);
            this.ui.addMessage(`Action executed: ${JSON.stringify(result)}`, 'system');
            this.stateManager.transition('idle');
            return result;
        } catch (error) {
            this.stateManager.handleError(error);
            this.ui.addMessage(`Action failed: ${error.message}`, 'system');
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new GiniAssistantApp();
    console.log('✅ GINI-AI Assistant UI ready');
});
function startVoice() {
  const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
  recognition.lang = 'en-IN';
  recognition.onresult = (e) => {
    document.getElementById('message-input').value = e.results[0][0].transcript;
  };
  recognition.start();
}
