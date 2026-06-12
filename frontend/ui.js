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

    // ─── Tab Switching with Master Theme Logic ──────────
    initTabs() {
        const sidebarItems    = document.querySelectorAll('.sidebar-item');
        const bottomNavItems  = document.querySelectorAll('#bottomNav .nav-item');
        const panels          = document.querySelectorAll('.tab-panel');
        const legacyNav       = document.querySelector('.legacy-nav-items');
        const masterNav       = document.querySelector('.chat-master-nav-items');

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

            // Toggle panels
            panels.forEach(p => {
                p.classList.toggle('active', p.id === `panel-${tabId}`);
            });

            // Chat Master Theme: activate when chat tab selected
            if (tabId === 'chat') {
                document.body.classList.add('chat-master-theme');
                if (legacyNav) legacyNav.style.display = 'none';
                if (masterNav) masterNav.style.display  = 'block';
                // Mirror the active state in the master nav buttons
                masterNav?.querySelectorAll('.sidebar-item').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.tab === 'chat');
                });
            } else {
                document.body.classList.remove('chat-master-theme');
                if (legacyNav) legacyNav.style.display = 'block';
                if (masterNav) masterNav.style.display  = 'none';
            }

            // Load memory vault when selected
            if (tabId === 'memory') window.app?.loadMemoryVault();
        };

        // Bind legacy sidebar tabs
        sidebarItems.forEach(item => {
            if (item.id === 'clearChatBtn') return;
            item.addEventListener('click', () => switchTab(item.dataset.tab));
        });

        // Bind mobile bottom nav
        bottomNavItems.forEach(item => {
            item.addEventListener('click', () => switchTab(item.dataset.tab));
        });

        // Portal home action buttons
        document.getElementById('heroOpenChatBtn')?.addEventListener('click', () => switchTab('chat'));
        document.getElementById('cardLaunchBtn')?.addEventListener('click',    () => switchTab('chat'));
        document.getElementById('heroExploreMemoryBtn')?.addEventListener('click', () => switchTab('memory'));

        this.switchTab = switchTab;
    }

    // ─── Gini Core Orb & Chat Parallax ──────────────────────
    initGiniCore() {
        // Set initial message time
        const initTimeEl = document.getElementById('initialMsgTime');
        if (initTimeEl) {
            initTimeEl.textContent = new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
        }

        // Master Design Orb Parallax — subtle mouse-tracking
        const chatPanel = document.getElementById('panel-chat');
        const orbBg     = document.getElementById('orbBackground');

        if (chatPanel && orbBg) {
            let targetX = 0, targetY = 0, currentX = 0, currentY = 0;
            let rafId = null;

            const tick = () => {
                currentX += (targetX - currentX) * 0.04;
                currentY += (targetY - currentY) * 0.04;
                orbBg.style.transform =
                    `translate(calc(-50% + ${currentX.toFixed(2)}px), calc(-50% + ${currentY.toFixed(2)}px))`;
                rafId = requestAnimationFrame(tick);
            };
            rafId = requestAnimationFrame(tick);

            chatPanel.addEventListener('mousemove', (e) => {
                const r = chatPanel.getBoundingClientRect();
                targetX = ((e.clientX - r.left) / r.width  - 0.5) * 22;
                targetY = ((e.clientY - r.top)  / r.height - 0.5) * 22;
            });
            chatPanel.addEventListener('mouseleave', () => { targetX = 0; targetY = 0; });
        }

        // Legacy Hero Card 3D tilt (existing functionality — unchanged)
        const container = this.elements.giniCoreContainer;
        const card      = this.elements.heroCard;
        if (!container || !card) return;

        let tX = 0, tY = 0, cX = 0, cY = 0;
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            tX = ((e.clientX - rect.left) / rect.width  - 0.5) * 2;
            tY = ((e.clientY - rect.top)  / rect.height - 0.5) * 2;
            container.classList.add('interactive-move');
        });
        card.addEventListener('mouseleave', () => {
            tX = 0; tY = 0;
            container.classList.remove('interactive-move');
        });
        const heroTick = () => {
            cX += (tX - cX) * 0.08;
            cY += (tY - cY) * 0.08;
            container.style.setProperty('--mx', cX);
            container.style.setProperty('--my', cY);
            card.style.transform = `perspective(1000px) rotateY(${cX * 6}deg) rotateX(${cY * -6}deg)`;
            requestAnimationFrame(heroTick);
        };
        heroTick();
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
        // Sanitize content and render line breaks
        p.textContent = content;
        messageDiv.appendChild(p);

        // Timestamp
        const timeEl = document.createElement('span');
        timeEl.className = 'message-time';
        timeEl.textContent = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        messageDiv.appendChild(timeEl);

        // Action bar for assistant messages
        if (role === 'assistant') {
            const actions = document.createElement('div');
            actions.className = 'message-actions';
            actions.innerHTML = [
                `<button title="Copy" aria-label="Copy message">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                    </svg>
                </button>`,
                `<button title="Like" aria-label="Like message">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/>
                        <path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                    </svg>
                </button>`,
                `<button title="Dislike" aria-label="Dislike message">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/>
                        <path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
                    </svg>
                </button>`,
                `<button title="Read aloud" aria-label="Read message aloud">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                        <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
                    </svg>
                </button>`,
            ].join('');

            // Wire action handlers
            const [copyBtn, likeBtn, dislikeBtn, speakBtn] = actions.querySelectorAll('button');
            copyBtn.addEventListener('click', () => {
                navigator.clipboard?.writeText(content).then(() => {
                    copyBtn.classList.add('active');
                    setTimeout(() => copyBtn.classList.remove('active'), 1500);
                });
            });
            likeBtn.addEventListener('click', () => {
                likeBtn.classList.toggle('active');
                dislikeBtn.classList.remove('active');
            });
            dislikeBtn.addEventListener('click', () => {
                dislikeBtn.classList.toggle('active');
                likeBtn.classList.remove('active');
            });
            speakBtn.addEventListener('click', () => {
                if (window.speechSynthesis) {
                    const utt = new SpeechSynthesisUtterance(content);
                    window.speechSynthesis.speak(utt);
                    speakBtn.classList.add('active');
                    utt.onend = () => speakBtn.classList.remove('active');
                }
            });

            messageDiv.appendChild(actions);
        }

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
                <div class="chat-date-divider"><span>Today</span></div>
                <div class="message assistant">
                    <p>Hi! I'm Gini.</p>
                    <p>How can I help you today?</p>
                    <span class="message-time">${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span>
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
        loadingDiv.innerHTML = '<p>Thinking</p><span class="dots"><span></span><span></span><span></span></span>';
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
