/**
 * GINI-AI UI Manager — Ecosystem Portal Upgraded
 * Handles workspace tabs, Gini Core states, cursor 3D hover tracking,
 * floating bubbles, SQLite memories rendering, and settings sync.
 */

class AssistantUIManager {
    constructor() {
        this.elements = {
            // General indicators
            statusDot: document.getElementById('status-dot'),
            statusText: document.getElementById('status-text'),
            currentState: document.getElementById('current-state'),
            lastEmotion: document.getElementById('last-emotion'),
            errorDisplay: document.getElementById('error-display'),
            assistantStatus: document.getElementById('assistant-status'),
            sessionId: document.getElementById('session-id'),
            userId: document.getElementById('user-id'),

            // Chat Interface elements
            messageInput: document.getElementById('message-input'),
            sendButton: document.getElementById('send-button'),
            chatMessages: document.getElementById('chat-messages'),
            inputHint: document.getElementById('input-hint'),
            clearChatBtn: document.getElementById('clearChatBtn'),

            // Gini Core
            giniCoreContainer: document.getElementById('giniCoreContainer'),
            giniCore: document.getElementById('giniCore'),
            heroCard: document.getElementById('heroCard'),

            // Tabs / Grid
            memoryGrid: document.getElementById('memoryGrid'),
            refreshMemoryBtn: document.getElementById('refreshMemoryBtn'),
            consoleLog: document.getElementById('consoleLog'),
            
            // Speech labs controls
            ttsVoiceSelect: document.getElementById('ttsVoiceSelect'),
            ttsRateRange: document.getElementById('ttsRateRange'),
            ttsPitchRange: document.getElementById('ttsPitchRange'),
            rateVal: document.getElementById('rateVal'),
            pitchVal: document.getElementById('pitchVal'),
            labsVoiceLoopToggle: document.getElementById('labsVoiceLoopToggle'),
        };

        this.emotionEmojis = {
            positive: '😊',
            negative: '😞',
            neutral: '😐',
        };

        // Initialize UI components
        this.initTabs();
        this.initGiniCore();
        this.initSpeechSliders();
    }

    // ─── Workspace Tabs Configuration ──────────────────────────
    initTabs() {
        const sidebarItems = document.querySelectorAll('.sidebar-item');
        const bottomNavItems = document.querySelectorAll('#bottomNav .nav-item');
        const panels = document.querySelectorAll('.tab-panel');

        const switchTab = (tabId) => {
            if (!tabId) return;
            console.log(`[UI] Switching workspace tab: ${tabId}`);

            // Deactivate all nav buttons
            sidebarItems.forEach(el => {
                if (el.dataset.tab === tabId) el.classList.add('active');
                else el.classList.remove('active');
            });
            bottomNavItems.forEach(el => {
                if (el.dataset.tab === tabId) el.classList.add('active');
                else el.classList.remove('active');
            });

            // Toggle panel active classes
            panels.forEach(p => {
                if (p.id === `panel-${tabId}`) {
                    p.classList.add('active');
                } else {
                    p.classList.remove('active');
                }
            });

            // Trigger data load if vault tab is active
            if (tabId === 'memory') {
                window.app?.loadMemoryVault();
            }
        };

        // Bind sidebar tabs
        sidebarItems.forEach(item => {
            if (item.id === 'clearChatBtn') return; // Skip action button
            item.addEventListener('click', () => switchTab(item.dataset.tab));
        });

        // Bind mobile bottom nav tabs
        bottomNavItems.forEach(item => {
            item.addEventListener('click', () => switchTab(item.dataset.tab));
        });

        // Bind portal home action buttons
        document.getElementById('heroOpenChatBtn')?.addEventListener('click', () => switchTab('chat'));
        document.getElementById('cardLaunchBtn')?.addEventListener('click', () => switchTab('chat'));
        document.getElementById('heroExploreMemoryBtn')?.addEventListener('click', () => switchTab('memory'));

        // Expose switch method
        this.switchTab = switchTab;
    }

    // ─── Gini Core Orb & Cursor 3D Tilting ──────────────────────
    initGiniCore() {
        const container = this.elements.giniCoreContainer;
        const card = this.elements.heroCard;
        if (!container || !card) return;

        let targetX = 0, targetY = 0;
        let currentX = 0, currentY = 0;

        // Mousemove listeners for tilt variables
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            // Normalized offset from card center (-1.0 to 1.0)
            const x = (e.clientX - rect.left) / rect.width - 0.5;
            const y = (e.clientY - rect.top) / rect.height - 0.5;

            // Scale displacement factors
            targetX = x * 2;
            targetY = y * 2;

            container.classList.add('interactive-move');
        });

        card.addEventListener('mouseleave', () => {
            targetX = 0;
            targetY = 0;
            container.classList.remove('interactive-move');
        });

        // Frame rendering loop
        const drawFrame = () => {
            // Lerp transition calculations
            currentX += (targetX - currentX) * 0.08;
            currentY += (targetY - currentY) * 0.08;

            container.style.setProperty('--mx', currentX);
            container.style.setProperty('--my', currentY);

            // Apply 3D perspective transform matrix
            card.style.transform = `perspective(1000px) rotateY(${currentX * 6}deg) rotateX(${currentY * -6}deg)`;

            requestAnimationFrame(drawFrame);
        };

        drawFrame();
    }

    // ─── Speech Slider Displays ────────────────────────────────
    initSpeechSliders() {
        const rateRange = this.elements.ttsRateRange;
        const pitchRange = this.elements.ttsPitchRange;

        if (rateRange) {
            rateRange.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value).toFixed(2);
                if (this.elements.rateVal) this.elements.rateVal.textContent = val;
                window.app?.updateSpeechConfig();
            });
        }

        if (pitchRange) {
            pitchRange.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value).toFixed(2);
                if (this.elements.pitchVal) this.elements.pitchVal.textContent = val;
                window.app?.updateSpeechConfig();
            });
        }
    }

    // ─── SQLite Memory Vault Visual Rendering ──────────────────
    renderMemoryGrid(memories) {
        const grid = this.elements.memoryGrid;
        if (!grid) return;

        grid.innerHTML = '';

        if (!memories || memories.length === 0) {
            grid.innerHTML = `<div class="empty-state">No facts stored in SQLite memory database yet. Say "Remember that my name is Anmol" to record.</div>`;
            return;
        }

        memories.forEach(mem => {
            const card = document.createElement('div');
            const catClass = mem.category ? `category-${mem.category.toLowerCase()}` : '';
            card.className = `memory-card ${catClass}`;

            const addedDate = mem.added_at ? new Date(mem.added_at).toLocaleString() : 'Recent';

            card.innerHTML = `
                <div class="memory-card-header">
                    <span class="memory-category">${mem.category || 'Fact'}</span>
                    <span class="memory-time">${addedDate}</span>
                </div>
                <div class="memory-text">"${mem.value}"</div>
                <div class="memory-topic">Topic: ${mem.topic}</div>
            `;
            grid.appendChild(card);
        });
    }

    // ─── Action Console Live Feed Log ──────────────────────────
    writeConsoleLog(message, status = 'system') {
        const logFeed = this.elements.consoleLog;
        if (!logFeed) return;

        const time = new Date().toLocaleTimeString();
        const entry = document.createElement('span');
        entry.className = `log-entry ${status}`;
        entry.innerHTML = `[${time}] ${message}`;

        logFeed.appendChild(entry);
        logFeed.scrollTop = logFeed.scrollHeight;
    }

    // ─── Standard Assistant UI Callbacks ────────────────────────
    updateState(stateInfo) {
        const { state, config, emotion, error } = stateInfo;

        // Update indicators
        if (this.elements.statusDot) {
            this.elements.statusDot.className = `status-dot ${config.color}`;
        }
        if (this.elements.statusText) {
            this.elements.statusText.textContent = config.label;
        }
        if (this.elements.currentState) {
            this.elements.currentState.textContent = state;
        }

        // Update Gini Core CSS classes
        if (this.elements.giniCoreContainer) {
            this.elements.giniCoreContainer.className = 'gini-core-container';
            this.elements.giniCoreContainer.classList.add(`state-${state}`);
        }

        // Update emotion emojis
        if (emotion && this.elements.lastEmotion) {
            const emoji = this.emotionEmojis[emotion] || '?';
            this.elements.lastEmotion.textContent = `${emoji} ${emotion}`;
        }

        // Input lockouts based on core state configs
        if (this.elements.messageInput) {
            this.elements.messageInput.disabled = !config.inputEnabled;
        }
        if (this.elements.sendButton) {
            this.elements.sendButton.disabled = !config.canSendMessage;
        }
        if (this.elements.inputHint) {
            this.elements.inputHint.textContent = config.hint;
        }

        // Handle error displays
        if (error) {
            this.showError(error);
        } else {
            this.hideError();
        }
    }

    addMessage(content, role = 'user') {
        if (!this.elements.chatMessages) return;

        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;

        const p = document.createElement('p');
        p.textContent = content;

        messageDiv.appendChild(p);
        this.elements.chatMessages.appendChild(messageDiv);
        this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
    }

    updateSessionInfo(userId, sessionId) {
        if (this.elements.userId) this.elements.userId.textContent = userId || 'default';
        if (this.elements.sessionId) this.elements.sessionId.textContent = sessionId || '—';
    }

    updateAssistantStatus(isRunning) {
        if (!this.elements.assistantStatus) return;
        this.elements.assistantStatus.textContent = isRunning ? '✅ Online' : '❌ Offline';
        this.elements.assistantStatus.className = isRunning ? 'online' : 'offline';
    }

    showError(errorMessage) {
        if (!this.elements.errorDisplay) return;
        this.elements.errorDisplay.textContent = `⚠️ Error: ${errorMessage}`;
        this.elements.errorDisplay.style.display = 'block';
    }

    hideError() {
        if (!this.elements.errorDisplay) return;
        this.elements.errorDisplay.style.display = 'none';
        this.elements.errorDisplay.textContent = '';
    }

    clearChat() {
        if (this.elements.chatMessages) {
            this.elements.chatMessages.innerHTML = `
                <div class="message system">
                    <p>👋 Messages cleared. I'm ready to start fresh.</p>
                </div>
            `;
        }
    }

    getInputAndClear() {
        if (!this.elements.messageInput) return '';
        const value = this.elements.messageInput.value.trim();
        this.elements.messageInput.value = '';
        return value;
    }

    focusInput() {
        this.elements.messageInput?.focus();
    }

    showLoadingIndicator() {
        if (!this.elements.chatMessages) return;
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'message system loading';
        loadingDiv.id = 'loading-indicator';
        loadingDiv.innerHTML = '<p>Thinking</p><span class="dots"></span>';
        this.elements.chatMessages.appendChild(loadingDiv);
        this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
    }

    removeLoadingIndicator() {
        const loading = document.getElementById('loading-indicator');
        if (loading) loading.remove();
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AssistantUIManager;
}
