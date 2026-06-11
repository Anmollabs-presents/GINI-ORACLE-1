# ============================================================
# GINI-ORACLE-1 — Resilience Layer Integration Guide
# docs/RESILIENCE.md
# ============================================================

## Overview

The resilience layer provides comprehensive error handling and recovery mechanisms for all critical failure modes in GINI-AI:

1. **Microphone failure** — Device unavailable, permission denied, busy
2. **Missing dependencies** — TTS, STT, voice packages
3. **App not found** — Registry lookup fails, suggest alternatives
4. **Invalid command** — Parsing/validation errors, suggest fixes
5. **Browser failure** — Launch failure, crash, suggest alternatives
6. **TTS crash** — Speech synthesis error, fallback to text
7. **STT timeout** — Recognition timeout, extend timeout or fallback
8. **Backend disconnect** — API unreachable, queue requests

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│              ResilienceCoordinator                          │
│         (Master orchestrator for all recovery)              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │             RecoveryManager                          │  │
│  │ • Circuit breakers  • Retry policies  • Logging      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ VoiceResil.  │  │ AppResil.    │  │ WebResil.        │ │
│  │ • Mic fail   │  │ • App lost   │  │ • Browser fail   │ │
│  │ • TTS crash  │  │ • Invalid cmd│  │ • URL invalid    │ │
│  │ • STT timeout│  │ • Permission │  │ • Connection err │ │
│  └──────────────┘  └──────────────┘  └──────────────────┘ │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          DependencyValidator                         │  │
│  │ • Check packages  • Check binaries  • Diagnose      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Key Patterns

#### 1. Circuit Breaker
Prevents cascading failures by temporarily disabling failed services.

```python
from core.resilience import CircuitBreaker, CircuitState

# Register circuit for microphone
circuit = recovery_manager.register_circuit(
    "microphone",
    failure_threshold=3,      # Open after 3 failures
    recovery_timeout=10       # Try recovery after 10s
)

# Use circuit
try:
    result = circuit.call(capture_audio)  # Raises if OPEN
except CircuitBreakerOpenError:
    # Use fallback (text input)
    pass
```

#### 2. Retry with Exponential Backoff
Automatically retry failed operations with increasing delays.

```python
policy = RetryPolicy(
    max_attempts=3,
    initial_delay=0.5,
    max_delay=10.0,
    backoff_factor=2.0,
    jitter=True  # Add randomness to avoid thundering herd
)

result = await policy.execute_async(
    func=api_call,
    on_retry=lambda attempt, error, delay: 
        log.warning(f"Retrying in {delay}s...")
)
```

#### 3. Failure Context Tracking
Record failures for monitoring and diagnostics.

```python
context = FailureContext(
    mode=FailureMode.MIC_FAILURE,
    message="No microphone devices found",
    service="voice_engine",
    recoverable=True,
    recovery_strategy=RecoveryStrategy.FALLBACK,
    metadata={"available_devices": 0}
)

recovery_manager.record_failure(context)
```

## Integration with Bootstrap

The resilience layer is automatically initialized during bootstrap:

```python
# core/bootstrap.py

async def bootstrap() -> tuple[GiniAssistant, LifecycleManager]:
    # ... existing bootstrap code ...

    # Initialize resilience layer
    log.info("▶ Initializing resilience layer...")
    resilience_coord = get_resilience_coordinator()
    if not await resilience_coord.initialize():
        log.warning("⚠️  Resilience layer initialization had issues")

    # Add self-healing hook
    lifecycle.add_startup_hook(
        "resilience_self_heal",
        resilience_coord.trigger_self_healing,
        critical=False,
    )

    return assistant, lifecycle
```

## Usage Patterns

### Pattern 1: Handle Error with Recovery

```python
from core.resilience_coordinator import get_resilience_coordinator
from core.resilience import FailureMode

coordinator = get_resilience_coordinator()

try:
    # Attempt operation
    result = capture_audio_from_mic()
except MicrophoneError as e:
    # Handle with recovery
    recovery = await coordinator.handle_error(
        failure_mode=FailureMode.MIC_FAILURE,
        error_message=str(e),
        context={"available_devices": devices}
    )
    
    # recovery = {
    #     "fallback_mode": "text_input",
    #     "message": "Microphone unavailable. Using text.",
    #     "can_retry": True
    # }
    
    if recovery["fallback_mode"] == "text_input":
        result = await get_text_input_from_user()
```

### Pattern 2: Validate Before Operation

```python
coordinator = get_resilience_coordinator()

# Check if voice is available
can_proceed, error = await coordinator.validate_before_operation(
    operation_type="voice_capture"
)

if not can_proceed:
    log.error(f"Cannot capture voice: {error}")
    # Fall back to text input
```

### Pattern 3: Queue for Retry (Offline Support)

```python
# When backend is unavailable
if backend_down:
    coordinator.queue_request_for_retry({
        "operation": "send_message",
        "message": user_message,
        "user_id": user_id,
        "timestamp": datetime.now()
    })
```

### Pattern 4: Check Health Before Critical Operations

```python
health = await coordinator.run_health_checks()

if not health.is_healthy:
    log.warning(f"System issues detected: {health.failures}")
    if "microphone" in str(health.failures):
        disable_voice_features()
    if "backend" in str(health.failures):
        enable_offline_mode()
```

## Recovery Strategies

### For Microphone Failures

1. **Try alternative device** → Select next audio input device
2. **Fallback to text** → Switch to text-only input
3. **Extend timeout** → Increase listening timeout
4. **Degrade gracefully** → Continue without voice

### For Missing Dependencies

1. **Install missing package** → Run `pip install [package]`
2. **Use alternative** → Switch to fallback package
3. **Disable feature** → Turn off feature that requires package
4. **Warn user** → Log warning, continue with degraded functionality

### For App Launch Failures

1. **Find similar app** → Suggest alternative apps
2. **Install app** → Offer to open app store
3. **Use web version** → Open web browser instead
4. **Suggest retry** → User may retry after fixing issue

### For Browser Failures

1. **Try alternative browser** → Chrome → Firefox → Edge
2. **Use text mode** → Display URL, instructions
3. **Queue for retry** → Try again later
4. **Graceful degradation** → Basic web functionality

### For Backend Disconnection

1. **Queue request** → Store request locally
2. **Retry with backoff** → Exponential retry
3. **Circuit breaker** → Stop hammering backend
4. **Offline mode** → Use cached data, local processing

## Monitoring and Diagnostics

### Get Current Status

```python
coordinator = get_resilience_coordinator()
status = coordinator.get_status()

# status = {
#     "initialized": true,
#     "healthy": false,
#     "uptime_seconds": 3600,
#     "subsystems": {
#         "voice": {"mic_available": false, ...},
#         "app": {...},
#         "web": {...},
#         "backend": {...},
#         "dependencies": {...}
#     },
#     "failure_report": {...},
#     "warnings": [...],
#     "recommendations": [...]
# }
```

### Get Full Diagnostics

```python
diagnostics = await coordinator.get_diagnostics()

# Includes:
# - Complete health status
# - Dependency check results
# - Circuit breaker states
# - Recent failure history
```

### Check Specific Subsystem

```python
voice_status = coordinator.voice_resilience.get_status()
# {"mic_available": true, "tts_enabled": true, ...}

app_status = coordinator.app_resilience.get_status()
# {"app_launcher_circuit": {...}}

web_status = coordinator.web_resilience.get_status()
# {"failed_browsers": [...], "circuits": {...}}
```

## API Reference

### ResilienceCoordinator

#### `async initialize() -> bool`
Initialize all resilience systems. Called during bootstrap.

#### `async run_health_checks() -> SystemHealth`
Run comprehensive health checks on all subsystems.

#### `async handle_error(failure_mode, error_message, context) -> dict`
Central error handler. Routes to appropriate recovery manager.

#### `async trigger_self_healing() -> dict`
Attempt to auto-heal all subsystems.

#### `get_status() -> dict`
Get comprehensive system status.

#### `get_health() -> dict`
Get detailed health report.

#### `async get_diagnostics() -> dict`
Get full diagnostic report.

#### `async validate_before_operation(operation_type, context) -> (bool, str)`
Validate system is ready for operation.

### VoiceResilienceManager

- `handle_mic_failure(error, devices)` — Recover from mic error
- `handle_stt_timeout(timeout)` — Recover from STT timeout
- `handle_tts_crash(error)` — Recover from TTS crash
- `get_status()` — Get voice system status
- `self_heal()` — Attempt auto-healing

### AppResilienceManager

- `handle_app_not_found(app_name)` — Find similar apps
- `handle_invalid_command(command, error)` — Suggest fixes
- `handle_permission_denied(command)` — Handle permissions
- `validate_app_name(name)` — Validate app name
- `validate_command(cmd)` — Validate command syntax

### WebResilienceManager

- `handle_browser_not_found(name)` — Try alternative browser
- `handle_browser_crash(name)` — Recover from crash
- `handle_invalid_url(url)` — Fix URL or search
- `handle_connection_timeout(url, timeout)` — Retry with backoff
- `validate_url(url)` — Validate URL safety

### DependencyValidator

- `check_all_dependencies()` — Run all checks
- `get_report()` — Get dependency report
- `get_recommendations()` — Get install suggestions

## Testing

See `tests/test_resilience.py` for comprehensive test examples.

```bash
# Run resilience tests
pytest tests/test_resilience.py -v

# Run with coverage
pytest tests/test_resilience.py --cov=core.resilience --cov-report=html
```

## Best Practices

1. **Always use recovery manager** — Don't catch exceptions without recovery
2. **Record failures** — Log all failures for diagnostics
3. **Validate before operations** — Use `validate_before_operation()`
4. **Graceful degradation** — Provide text fallbacks for voice failures
5. **User-friendly messages** — Use recovery action messages directly to user
6. **Monitor health** — Periodically call `run_health_checks()`
7. **Self-heal proactively** — Call `trigger_self_healing()` on startup
8. **Queue offline requests** — Use `queue_request_for_retry()` when offline

## Troubleshooting

### System shows "unhealthy" on startup
1. Run `coordinator.get_diagnostics()` to see what failed
2. Check dependency report for missing packages
3. Install missing packages with suggested commands
4. Restart system

### Microphone not detected
1. Check `voice_resilience.get_status()` for mic status
2. List available devices: `await voice_resilience.detect_audio_devices()`
3. Try alternative device: `await voice_resilience.switch_audio_device(1)`
4. Check system audio settings

### Circuit breaker stuck OPEN
1. Wait for `recovery_timeout` seconds
2. Or manually reset: `circuit.state = CircuitState.CLOSED`
3. System will automatically attempt recovery

### Backend won't reconnect
1. Check backend is running: `coordinator.backend_resilience.check_backend_health()`
2. Verify network connectivity
3. Check backend logs for errors
4. Requests are queued and will retry when backend comes back

## Performance Implications

- **Circuit breakers**: ~1ms overhead per call
- **Retry policy**: Async, no blocking
- **Health checks**: ~500ms-1s for full check
- **Self-healing**: ~100ms-500ms depending on subsystems
- **Memory**: ~100KB for resilience structures

## Security Considerations

- URL validation blocks dangerous schemes (javascript:, file://, etc)
- Command validation prevents shell injection
- App names validated before execution
- All errors logged but sensitive data sanitized
- Retry policies have exponential backoff (prevents DoS)
