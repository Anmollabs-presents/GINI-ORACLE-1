# Frontend-Backend Integration Guide

## Prerequisites

### Backend
- Python 3.10+
- FastAPI 0.111.0
- Uvicorn 0.29.0
- SQLite (automatic)

### Frontend
- Any modern web browser
- Python 3.6+ (for local dev server) OR Node.js (for http-server)

## Quick Start

### 1. Start Backend

```bash
cd backend/gini-ai-python

# Install dependencies
pip install -r requirements.txt

# Run backend
python main.py
```

Expected output:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
✅ Bootstrap complete
```

Verify health:
```bash
curl http://localhost:8000/health
```

### 2. Start Frontend

```bash
cd frontend

# Option A: Python built-in server
python -m http.server 3000

# Option B: Python dev server (CORS enabled)
python server.py

# Option C: Node.js http-server
npx http-server -p 3000
```

Expected output:
```
Serving on http://localhost:3000
```

### 3. Open in Browser

Navigate to `http://localhost:3000`

You should see:
- Status indicator showing "🟢 Idle"
- Backend status: "✅ Running"
- Input field enabled
- Empty chat area

## State Transitions - Manual Testing

### Test 1: Send a Simple Message

1. Type: `"Hello Gini"`
2. Click Send
3. Observe state changes:
   - 🔵 "Listening" (200ms)
   - 🟣 "Thinking" (actual backend processing)
   - 🟠 "Speaking" (500ms)
   - 🟢 "Idle" (ready)
4. Chat should show:
   - Your message: "Hello Gini"
   - Assistant response: "[response from backend]"
   - Emotion indicator: "😊 positive" or similar

### Test 2: Knowledge Question

1. Type: `"What is photosynthesis?"`
2. Send
3. Backend should respond with definition from Q&A handler
4. Observe emotion indicator

### Test 3: Memory Store

1. Type: `"Remember that I like dark mode"`
2. Send
3. Response: Should acknowledge storing fact
4. Follow up: Type `"What do I like?"`
5. Response: Should recall "dark mode"

### Test 4: Error Handling

1. **Backend offline:** Stop backend, try sending message
   - Frontend should show "Error: fetch failed"
   - State transitions to ERROR
   - Input stays enabled
   - Error message displayed in UI

2. **Invalid message:** Try sending empty message
   - Button disabled for empty input
   - Nothing sent

3. **Recovery:** Restart backend
   - Health check automatically attempts
   - After sending next message, should work

### Test 5: Quick Actions

Click any quick action button (e.g., "What is photosynthesis?")
- Input field auto-populates
- Send button auto-triggered
- Should work same as manual message

## State Verification Checklist

### IDLE State ✓
- [ ] Status dot: 🟢 Green
- [ ] Input field: Enabled
- [ ] Send button: Enabled
- [ ] Hint text: "Ready to assist"
- [ ] User can type and send

### LISTENING State ✓
- [ ] Status dot: 🔵 Blue
- [ ] Input field: Disabled (grayed out)
- [ ] Send button: Disabled
- [ ] Hint text: "Processing your input..."
- [ ] Lasts ~200ms

### THINKING State ✓
- [ ] Status dot: 🟣 Purple
- [ ] Input field: Disabled
- [ ] Send button: Disabled
- [ ] Hint text: "Analyzing your request..."
- [ ] Loading indicator in chat
- [ ] Lasts until backend responds

### SPEAKING State ✓
- [ ] Status dot: 🟠 Orange
- [ ] Input field: Disabled
- [ ] Send button: Disabled
- [ ] Hint text: "Generating response..."
- [ ] Assistant message visible
- [ ] Emotion indicator shows
- [ ] Lasts ~500ms

### EXECUTING State (Optional) ✓
- [ ] Status dot: 🩷 Pink
- [ ] Input field: Disabled
- [ ] Send button: Disabled
- [ ] Used for action execution
- [ ] Transitions back to IDLE

### ERROR State ✓
- [ ] Status dot: 🔴 Red
- [ ] Input field: Enabled (can retry)
- [ ] Send button: Disabled
- [ ] Error message displayed in red
- [ ] Error description shown in UI
- [ ] User can type new message or retry

## API Endpoint Testing

### Using Browser Console

```javascript
// Check API client
console.log(app.api);

// Test health endpoint
app.api.getHealth().then(h => console.log(h));

// Test status endpoint
app.api.getStatus().then(s => console.log(s));

// Test send message (bypasses UI state machine)
app.api.sendMessage("Test").then(r => console.log(r));

// Check state
console.log(app.stateManager.getStateInfo());

// Manually transition state
app.stateManager.transition('thinking');
app.stateManager.transition('idle');
```

### Using curl (Backend Verification)

```bash
# Health check
curl http://localhost:8000/health

# Status
curl http://localhost:8000/status

# Chat message
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "user_id": "test_user"}'

# Action execution
curl -X POST http://localhost:8000/action \
  -H "Content-Type: application/json" \
  -d '{"intent": "smart_home.lights.on", "payload": {"room": "kitchen"}}'
```

## Session Management

### Verify Session Persistence

1. Send message: "Hello"
   - Note session ID in UI: e.g., `sess_abc123`
2. Send follow-up: "How are you?"
   - Same session ID should persist
   - Backend should maintain conversation history

### Check Backend Memory

```bash
# Backend logs should show:
# [session_id: sess_abc123] Turn: user - "Hello"
# [session_id: sess_abc123] Turn: assistant - "[response]"
```

## Debugging

### Browser Console Logs

Enable detailed logging:
```javascript
// app.js already logs initialization
// check console for:
// ✅ GINI-AI Assistant UI ready
// ✅ Backend is healthy
```

### Network Tab

1. Open DevTools → Network tab
2. Send message
3. Verify:
   - POST /chat request succeeds (200)
   - Request payload contains message, user_id, session_id
   - Response includes response, emotion, user_id, session_id

### Backend Logs

```bash
# Should show:
# INFO:     127.0.0.1:52345 - "POST /chat HTTP/1.1" 200 OK
# [session_id] Chat processed
```

## Common Issues

### Issue 1: "Backend is not responding"
**Solution:**
- Verify backend is running: `ps aux | grep main.py`
- Check port: `curl http://localhost:8000/health`
- If different port, edit `app.js`: `new GiniAPIClient('http://localhost:PORT')`

### Issue 2: CORS Errors in Console
**Solution:**
- Backend CORS must allow frontend origin
- Edit `main.py`:
  ```python
  allow_origins=["http://localhost:3000", "http://localhost:8000"],
  ```

### Issue 3: Input Stuck Disabled After Error
**Solution:**
- This is expected (safety feature)
- Try typing another message
- Or refresh page

### Issue 4: Session ID Shows "—"
**Solution:**
- Session created only after first message sent
- Send any message first

## Integration Checklist

- [ ] Backend runs on port 8000
- [ ] Frontend serves on port 3000 (or 8000)
- [ ] CORS enabled on backend
- [ ] All 6 state colors render (green, blue, purple, orange, pink, red)
- [ ] Message sending works (user input → chat display)
- [ ] Response shows (assistant message → chat display)
- [ ] Emotion indicator works (shows emoji + emotion word)
- [ ] Session ID persists across messages
- [ ] Error messages display clearly
- [ ] Backend disconnect gracefully shows error
- [ ] Recovery after error works

## Performance Notes

- State transitions: < 50ms
- Message display: Instant
- Backend round-trip: ~50-500ms (depends on backend processing)
- Network latency: Typically 10-50ms on localhost
- Chat scroll: Smooth (100+ messages)

## Next Steps

1. **Production Deployment:**
   - Move frontend to web server (nginx, Apache)
   - Update API base URL to production backend
   - Configure CORS for production domain

2. **Advanced Features:**
   - WebSocket for real-time updates
   - Voice input/output
   - Message history export
   - User profile management

3. **Testing:**
   - Automated end-to-end tests
   - Load testing
   - Browser compatibility testing

4. **Monitoring:**
   - Error tracking (Sentry, LogRocket)
   - Analytics (session duration, message count)
   - Performance monitoring
