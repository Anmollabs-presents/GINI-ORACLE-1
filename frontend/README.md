# GINI-AI Frontend

Modern web-based UI for GINI-AI Assistant with state-integrated communication.

## Features

✅ **State Management** — 6-state machine (idle, listening, thinking, speaking, executing, error)  
✅ **API Integration** — RESTful HTTP client for backend communication  
✅ **Real-time Status** — Live status indicators and session tracking  
✅ **Responsive Design** — Works on desktop and mobile browsers  
✅ **Chat Interface** — User-friendly message display with emotion indicators  
✅ **Error Handling** — Graceful error messages and recovery  

## Architecture

### State Machine
The UI implements a finite state machine with 6 states:

```
┌─────────┐
│  IDLE   │ (Ready, input enabled)
└────┬────┘
     │ User sends message
     ▼
┌───────────┐
│ LISTENING │ (Processing input)
└─────┬─────┘
      │
      ▼
┌──────────┐
│ THINKING │ (Waiting for response)
└────┬─────┘
     │
     ▼
┌─────────┐
│ SPEAKING│ (Generating response)
└────┬────┘
     │
     ▼
┌──────────┐
│ EXECUTING│ (Running action, optional)
└────┬─────┘
     │
     ▼
┌─────────┐
│  IDLE   │ (Ready again)
└─────────┘

On error:
     ▼
┌───────┐
│ ERROR │ (Input enabled, can retry)
└───┬───┘
    │
    ▼
┌─────────┐
│  IDLE   │ (After user recovers)
└─────────┘
```

### Components

**api.js** — `GiniAPIClient`
- Handles all HTTP communication with backend
- Methods: `getStatus()`, `getHealth()`, `sendMessage()`, `executeAction()`, `getPlugins()`
- Error handling and retry logic

**state.js** — `AssistantStateManager`
- Maintains UI state machine
- Provides `transition(newState, data)` method
- Notifies subscribers on state change
- Stores session/user context

**ui.js** — `AssistantUIManager`
- DOM manipulation and updates
- Renders chat messages, status indicators, error displays
- Manages input enabled/disabled states
- Updates emotion and session info

**app.js** — `GiniAssistantApp`
- Integrates all components
- Handles user interactions (send message, quick actions)
- Orchestrates backend calls and state transitions

## State Flow for Message Sending

```
User Input
    │
    ▼
app.handleSendMessage()
    │
    ├─ stateManager.transition('listening')    [UI freezes input]
    │
    ├─ await delay(200ms)                      [Simulate listening]
    │
    ├─ stateManager.transition('thinking')     [Show thinking status]
    │
    ├─ api.sendMessage(message, userId, sessionId)  [POST /chat]
    │
    ├─ ui.addMessage(response.response, 'assistant')  [Show response]
    │
    ├─ stateManager.transition('speaking', { emotion, sessionId })  [Show emotion]
    │
    ├─ await delay(500ms)                      [Simulate speaking]
    │
    └─ stateManager.transition('idle')         [Re-enable input]
```

## Backend Integration

### API Endpoints Used

**POST /chat**
- Request: `{ user_id, message, session_id? }`
- Response: `{ response, emotion, user_id, session_id, timestamp }`

**GET /health**
- Response: `{ status, app_name, version, environment, checks_passed, checks_failed, timestamp }`

**GET /status**
- Response: `{ assistant: {...}, lifecycle: {...}, timestamp }`

**POST /action**
- Request: `{ intent, payload }`
- Response: `{ status, module, ... }`

### CORS Configuration
Backend must allow frontend origin:
```python
# main.py
CORSMiddleware(
    app,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Or ["*"] for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Running the Frontend

### Option 1: Simple HTTP Server (Python)
```bash
cd frontend
python -m http.server 8000
# Open: http://localhost:8000
```

### Option 2: Node.js HTTP Server
```bash
cd frontend
npx http-server -p 8000
# Open: http://localhost:8000
```

### Option 3: Live Server (VS Code Extension)
1. Install "Live Server" extension in VS Code
2. Right-click `index.html` → "Open with Live Server"

## Backend Setup

Ensure backend is running before opening frontend:

```bash
cd backend/gini-ai-python
pip install -r requirements.txt
python main.py
# Starts on http://localhost:8000
```

## Browser Compatibility

- Chrome/Edge: ✅ Full support
- Firefox: ✅ Full support
- Safari: ✅ Full support
- Mobile browsers: ✅ Responsive design

## File Structure

```
frontend/
├── index.html          # Main HTML page
├── api.js             # API client
├── state.js           # State management
├── ui.js              # UI manager
├── app.js             # Main application
├── styles.css         # Styling
├── README.md          # This file
└── server.py          # Development server (optional)
```

## Configuration

### API Base URL
Edit `app.js` constructor:
```javascript
this.api = new GiniAPIClient('http://localhost:8000');  // Change if backend on different port
```

### Session/User Info
Edit `state.js`:
```javascript
this.userId = 'default';  // Change default user ID
```

## Development

### Adding New State
1. Update `state.js` `stateConfig` object
2. Add CSS class in `styles.css` (e.g., `.status-dot.newstate`)
3. Update state transitions in `app.js` as needed

### Customizing UI
- Edit `styles.css` for appearance
- Edit `ui.js` for DOM manipulation logic
- Edit `index.html` for HTML structure

### Testing State Machine
```javascript
// In browser console
app.stateManager.transition('error', { error: 'Test error' });
app.stateManager.transition('idle');
```

## Error Handling

The UI gracefully handles:
- Backend disconnection (shows "Backend is not responding")
- Network timeouts (shows error message in chat)
- Invalid session (auto-creates new session)
- Malformed responses (logs to console, shows generic error)

## Session Management

- Session ID is automatically created by backend on first message
- Frontend stores session ID in `stateManager.sessionId`
- All subsequent messages use same session for conversation history
- Each browser window/tab can have separate sessions

## Logging

Check browser console for debugging:
```
✅ GINI-AI Assistant UI ready
✅ Backend is healthy
[API request logs]
[State transition logs]
```

## Future Enhancements

- [ ] WebSocket support for real-time state updates
- [ ] Voice input integration (Web Speech API)
- [ ] Chat export/history download
- [ ] Dark/light theme toggle
- [ ] Settings panel (backend URL, user preferences)
- [ ] Plugin management UI
- [ ] Conversation history sidebar
- [ ] Typing indicators
