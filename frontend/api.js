/**
 * GINI-AI API Client
 * Handles all communication with the backend
 */

class GiniAPIClient {
    constructor(baseURL = 'https://gini-ag1b.onrender.com') {
        this.baseURL = baseURL;
        this.headers = {
            'Content-Type': 'application/json',
        };
        this.timeoutMs = 10000;
        this.pendingQueue = [];
    }

    async _fetchWithTimeout(url, options = {}) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
        try {
            return await fetch(url, { ...options, signal: controller.signal });
        } finally {
            clearTimeout(timeout);
        }
    }

    _backendDisconnectRecovery(error, request = null) {
        if (request) this.pendingQueue.push(request);
        return {
            status: 'degraded',
            failure_mode: 'backend_disconnect',
            fallback_mode: 'queue_request',
            message: 'Backend is unavailable. I queued the request and will retry when it reconnects.',
            can_retry: true,
            queued_requests: this.pendingQueue.length,
            error: error?.message || String(error),
        };
    }

    /**
     * Fetch system status
     */
    async getStatus() {
        try {
            const response = await this._fetchWithTimeout(`${this.baseURL}/status`, {
                method: 'GET',
                headers: this.headers,
            });
            if (!response.ok) throw new Error(`Status ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('Failed to get status:', error);
            return this._backendDisconnectRecovery(error);
        }
    }

    /**
     * Health check
     */
    async getHealth() {
        try {
            const response = await this._fetchWithTimeout(`${this.baseURL}/health`, {
                method: 'GET',
                headers: this.headers,
            });
            if (!response.ok) throw new Error(`Status ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('Failed to get health:', error);
            return this._backendDisconnectRecovery(error);
        }
    }

    /**
     * Send message to assistant
     */
    async sendMessage(message, userId = 'default', sessionId = null) {
        try {
            const payload = {
                message,
                user_id: userId,
                session_id: sessionId,
            };

            const response = await this._fetchWithTimeout(`${this.baseURL}/chat`, {
                method: 'POST',
                headers: this.headers,
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Failed to send message:', error);
            return {
                response: 'Backend is unavailable. Your message has been queued for retry.',
                emotion: 'neutral',
                user_id: userId,
                session_id: sessionId,
                recovery: this._backendDisconnectRecovery(error, {
                    endpoint: '/chat',
                    payload: { message, user_id: userId, session_id: sessionId },
                }),
            };
        }
    }

    /**
     * Execute an action
     */
    async executeAction(intent, payload = {}) {
        try {
            const response = await this._fetchWithTimeout(`${this.baseURL}/action`, {
                method: 'POST',
                headers: this.headers,
                body: JSON.stringify({
                    intent,
                    payload,
                }),
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Failed to execute action:', error);
            return this._backendDisconnectRecovery(error, {
                endpoint: '/action',
                payload: { intent, payload },
            });
        }
    }

    /**
     * Get plugin list
     */
    async getPlugins() {
        try {
            const response = await this._fetchWithTimeout(`${this.baseURL}/plugins`, {
                method: 'GET',
                headers: this.headers,
            });

            if (!response.ok) throw new Error(`Status ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('Failed to get plugins:', error);
            return { plugins: [], recovery: this._backendDisconnectRecovery(error) };
        }
    }

    async retryQueuedRequests() {
        const queued = [...this.pendingQueue];
        this.pendingQueue = [];
        const results = [];

        for (const request of queued) {
            if (request.endpoint === '/chat') {
                const { message, user_id, session_id } = request.payload;
                results.push(await this.sendMessage(message, user_id, session_id));
            } else if (request.endpoint === '/action') {
                const { intent, payload } = request.payload;
                results.push(await this.executeAction(intent, payload));
            }
        }

        return results;
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = GiniAPIClient;
}
