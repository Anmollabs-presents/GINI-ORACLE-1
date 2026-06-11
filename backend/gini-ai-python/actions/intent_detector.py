# ============================================================
# GINI-ORACLE-1 — Intent Detector
# actions/intent_detector.py
# ============================================================
"""
Detects intent from a ParsedCommand using keyword + pattern matching
with confidence scoring.

Intent categories:
  app_control     — open/close/launch apps
  system_control  — volume, brightness, wifi, shutdown
  media_control   — play/pause/skip music/video
  web_search      — search, look up, find online
  utility         — timer, alarm, reminder, calculator
  question_answer — general knowledge, who/what/where/why
  memory          — remember, recall, forget
  unknown         — nothing matched or confidence too low

Each detector returns an IntentResult with:
  - intent name
  - confidence score (0.0 – 1.0)
  - matched keywords
  - extracted action/sub-intent
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from actions.command_parser import ParsedCommand
from utils.logger import get_logger

log = get_logger(__name__)

# ── Confidence thresholds ─────────────────────────────────────
CONFIDENCE_HIGH    = 0.80
CONFIDENCE_MEDIUM  = 0.55
CONFIDENCE_LOW     = 0.30
CONFIDENCE_MINIMUM = 0.20   # Below this → unknown

# ── Intent name constants ─────────────────────────────────────
INTENT_APP_CONTROL     = "app_control"
INTENT_SYSTEM_CONTROL  = "system_control"
INTENT_MEDIA_CONTROL   = "media_control"
INTENT_WEB_SEARCH      = "web_search"
INTENT_UTILITY         = "utility"
INTENT_QUESTION_ANSWER = "question_answer"
INTENT_MEMORY          = "memory"
INTENT_UNKNOWN         = "unknown"

ALL_INTENTS = [
    INTENT_APP_CONTROL,
    INTENT_SYSTEM_CONTROL,
    INTENT_MEDIA_CONTROL,
    INTENT_WEB_SEARCH,
    INTENT_UTILITY,
    INTENT_QUESTION_ANSWER,
    INTENT_MEMORY,
    INTENT_UNKNOWN,
]


@dataclass
class IntentResult:
    """Result of intent detection for a single category."""
    intent: str
    confidence: float                       # 0.0 – 1.0
    matched_keywords: List[str] = field(default_factory=list)
    sub_intent: Optional[str] = None       # e.g. "play", "pause", "search"
    entities: Dict = field(default_factory=dict)
    is_confident: bool = False

    def __post_init__(self):
        self.is_confident = self.confidence >= CONFIDENCE_MEDIUM

    @property
    def label(self) -> str:
        return f"{self.intent}({self.confidence:.2f})"


# ── Keyword maps per intent ───────────────────────────────────

_APP_KEYWORDS = {
    "open":    0.6, "launch":  0.6, "start":   0.5,
    "close":   0.6, "exit":    0.6, "quit":    0.6,
    "run":     0.4, "install": 0.7, "uninstall": 0.7,
    "app":     0.4, "browser": 0.5, "chrome":  0.6,
    "focus":   0.7, "switch":  0.5, "bring":   0.4,
    "kill":    0.8, "force":   0.4, "terminate":0.7,
    "spotify": 0.7, "youtube": 0.6, "maps":    0.6,
    "whatsapp":0.7, "camera":  0.5, "gallery": 0.6,
    "settings":0.5, "files":   0.4,
}

_SYSTEM_KEYWORDS = {
    "volume":     0.8, "brightness": 0.8, "wifi":       0.7,
    "bluetooth":  0.7, "airplane":   0.8, "shutdown":   0.9,
    "restart":    0.9, "reboot":     0.9, "sleep":      0.7,
    "mute":       0.8, "unmute":     0.8, "silent":     0.7,
    "louder":     0.7, "quieter":    0.7, "dim":        0.7,
    "hotspot":    0.8, "battery":    0.6, "storage":    0.5,
    "screen":     0.4, "rotate":     0.6, "dark mode":  0.8,
    "do not disturb": 0.9, "dnd":    0.8,
    "lock":       0.9, "lock screen": 0.9, "lock computer":0.9,
}

_MEDIA_KEYWORDS = {
    "play":     0.7, "pause":   0.8, "resume":  0.7,
    "stop":     0.5, "next":    0.6, "previous":0.6,
    "skip":     0.7, "rewind":  0.7, "forward": 0.6,
    "music":    0.6, "song":    0.6, "track":   0.6,
    "video":    0.6, "movie":   0.6, "podcast": 0.7,
    "shuffle":  0.8, "repeat":  0.7, "playlist":0.7,
    "stream":   0.6, "watch":   0.5, "listen":  0.5,
}

_WEB_KEYWORDS = {
    "search":   0.9, "google":  0.9, "look up": 0.8,
    "find":     0.5, "browse":  0.7, "website": 0.6,
    "internet": 0.6, "online":  0.6, "web":     0.7,
    "youtube":  0.95,"wikipedia":0.8, "wiki":    0.7,
    "news":     0.6, "weather": 0.7, "wikipedia":0.8,
    "translate":0.8, "map":     0.6, "navigate": 0.7,
    "directions":0.8,"route":   0.6,
}

_UTILITY_KEYWORDS = {
    "timer":      0.9, "alarm":    0.9, "reminder": 0.9,
    "remind":     0.8, "set":      0.3, "schedule": 0.7,
    "calculate":  0.9, "calc":     0.8, "math":     0.7,
    "convert":    0.8, "currency": 0.8, "time":     0.4,
    "date":       0.5, "calendar": 0.7, "note":     0.7,
    "notepad":    0.7, "todo":     0.8, "task":     0.6,
    "countdown":  0.9, "stopwatch":0.9,
}

_QA_KEYWORDS = {
    "what":     0.5, "who":     0.5, "where":   0.5,
    "when":     0.5, "why":     0.5, "how":     0.4,
    "tell me":  0.6, "explain": 0.7, "define":  0.8,
    "meaning":  0.7, "difference":0.6, "compare":0.6,
    "describe": 0.6, "history": 0.5, "fact":    0.6,
    "trivia":   0.7, "know":    0.3,
}

_MEMORY_KEYWORDS = {
    "remember":      0.9, "recall":      0.9, "forget":      0.8,
    "memorize":      0.9, "store":       0.6, "save":        0.5,
    "my name":       0.7, "i am":        0.4, "i like":      0.5,
    "i prefer":      0.6, "i hate":      0.5, "note that":   0.8,
    "keep in mind":  0.9, "don't forget":0.9,
    # Recall-query anchors: ensure "what is my X" queries outscore QA
    "my":            0.3, "what is my":  0.6, "what project": 0.5,
    "who am i":      0.8, "what am i":  0.6,
}


class IntentDetector:
    """
    Scores all 8 intent categories against a ParsedCommand
    and returns the best match with confidence.
    """

    def detect(self, cmd: ParsedCommand) -> IntentResult:
        """
        Run all detectors, pick highest confidence result.
        Falls back to UNKNOWN if nothing crosses minimum threshold.
        """
        if not cmd.tokens:
            return IntentResult(intent=INTENT_UNKNOWN, confidence=0.0)

        candidates: List[IntentResult] = [
            self._score_app_control(cmd),
            self._score_system_control(cmd),
            self._score_media_control(cmd),
            self._score_web_search(cmd),
            self._score_utility(cmd),
            self._score_question_answer(cmd),
            self._score_memory(cmd),
        ]

        # Sort by confidence descending
        candidates.sort(key=lambda r: r.confidence, reverse=True)
        best = candidates[0]

        if best.confidence < CONFIDENCE_MINIMUM:
            log.debug(f"Intent: UNKNOWN (best was {best.label})")
            return IntentResult(intent=INTENT_UNKNOWN, confidence=best.confidence)

        log.info(f"Intent detected: {best.label} | sub={best.sub_intent} | keys={best.matched_keywords}")
        return best

    def detect_all(self, cmd: ParsedCommand) -> List[IntentResult]:
        """Return scored results for ALL intents (for debugging/analysis)."""
        results = [
            self._score_app_control(cmd),
            self._score_system_control(cmd),
            self._score_media_control(cmd),
            self._score_web_search(cmd),
            self._score_utility(cmd),
            self._score_question_answer(cmd),
            self._score_memory(cmd),
        ]
        return sorted(results, key=lambda r: r.confidence, reverse=True)

    # ── Individual scorers ────────────────────────────────────

    def _score_app_control(self, cmd: ParsedCommand) -> IntentResult:
        matched, score = self._keyword_score(cmd, _APP_KEYWORDS)
        sub = None
        if cmd.has_any("kill", "terminate"):
            sub = "kill"
        elif cmd.has_any("focus", "switch"):
            sub = "focus"
        elif cmd.has_any("browser", "browse") and not cmd.has_any("open","launch","start"):
            sub = "browser"
        elif cmd.has_any("open", "launch", "start", "run"):
            sub = "open" if not cmd.has_any("browser") else "browser"
        elif cmd.has_any("close", "exit", "quit"):
            sub = "close"
        elif cmd.has_any("install"):
            sub = "install"
        return IntentResult(INTENT_APP_CONTROL, score, matched, sub_intent=sub)

    def _score_system_control(self, cmd: ParsedCommand) -> IntentResult:
        matched, score = self._keyword_score(cmd, _SYSTEM_KEYWORDS)
        # Boost for explicit device-level commands
        if cmd.has_any("shutdown", "restart", "reboot"):
            score = min(1.0, score + 0.2)
        sub = self._extract_system_sub(cmd)
        return IntentResult(INTENT_SYSTEM_CONTROL, score, matched, sub_intent=sub)

    def _score_media_control(self, cmd: ParsedCommand) -> IntentResult:
        matched, score = self._keyword_score(cmd, _MEDIA_KEYWORDS)
        sub = None
        if cmd.has_any("play", "resume"):  sub = "play"
        elif cmd.has_any("pause"):         sub = "pause"
        elif cmd.has_any("stop"):          sub = "stop"
        elif cmd.has_any("next", "skip"):  sub = "next"
        elif cmd.has_any("previous"):      sub = "previous"
        elif cmd.has_any("shuffle"):       sub = "shuffle"
        return IntentResult(INTENT_MEDIA_CONTROL, score, matched, sub_intent=sub)

    def _score_web_search(self, cmd: ParsedCommand) -> IntentResult:
        matched, score = self._keyword_score(cmd, _WEB_KEYWORDS)
        # Boost: "search for X" pattern
        if cmd.starts_with_any("search", "google", "find", "look"):
            score = min(1.0, score + 0.2)
        # URL in command → strong web signal
        if "url" in cmd.entities:
            score = min(1.0, score + 0.3)
        if cmd.has_any("youtube"):
            sub = "youtube"
        elif cmd.has_any("wikipedia", "wiki"):
            sub = "wikipedia"
        elif cmd.has_any("google") and not cmd.has_any("maps"):
            sub = "google"
        elif cmd.has_any("map", "maps", "navigate", "directions", "route"):
            sub = "maps"
        elif cmd.has_any("weather"):
            sub = "weather"
        elif cmd.has_any("news"):
            sub = "news"
        elif cmd.has_any("translate"):
            sub = "translate"
        else:
            sub = "search" if cmd.has_any("search", "look") else "navigate"
        return IntentResult(INTENT_WEB_SEARCH, score, matched, sub_intent=sub)

    def _score_utility(self, cmd: ParsedCommand) -> IntentResult:
        matched, score = self._keyword_score(cmd, _UTILITY_KEYWORDS)
        sub = None
        if cmd.has_any("timer", "countdown"):    sub = "timer"
        elif cmd.has_any("alarm"):                sub = "alarm"
        elif cmd.has_any("reminder", "remind"):  sub = "reminder"
        elif cmd.has_any("calculate", "calc"):   sub = "calculate"
        elif (
            cmd.contains("what time") or
            cmd.contains("whats the time") or
            cmd.contains("current time") or
            cmd.contains("time is it")
        ):
            sub = "time"
            score = min(1.0, score + 0.4)
        elif cmd.has_any("date") and (cmd.is_question or cmd.has_any("today", "todays")):
            sub = "date"
            score = min(1.0, score + 0.4)
        elif cmd.has_any("convert", "currency"):  sub = "convert"
        elif cmd.has_any("note", "notepad"):      sub = "note"
        return IntentResult(INTENT_UTILITY, score, matched, sub_intent=sub)

    def _score_question_answer(self, cmd: ParsedCommand) -> IntentResult:
        matched, score = self._keyword_score(cmd, _QA_KEYWORDS)
        # Questions are a strong signal
        if cmd.is_question:
            score = min(1.0, score + 0.25)
        return IntentResult(INTENT_QUESTION_ANSWER, score, matched, sub_intent="qa")

    def _score_memory(self, cmd: ParsedCommand) -> IntentResult:
        matched, score = self._keyword_score(cmd, _MEMORY_KEYWORDS)
        sub = None

        # ── Recall detection ─────────────────────────────────────────
        # IMPORTANT: cmd.has_any() matches single tokens only.
        # For multi-word phrases use cmd.contains() (substring on normalized).
        _recall_contains = (
            "what is my",
            "what's my",
            "whats my",
            "who am i",
            "who do i",
            "what am i building",
            "what am i working",
            "what project am i",
            "do you remember",
            "do you know my",
        )
        is_recall = (
            any(cmd.contains(phrase) for phrase in _recall_contains)
            or (cmd.contains("my name") and cmd.is_question)
        )

        if is_recall:
            sub = "recall"
            # Boost large enough that even a zero-base-score recall query
            # (e.g. "what is my favorite color") wins over QA's 0.75.
            score = min(1.0, score + 0.65)

        # ── Store detection ───────────────────────────────────────────
        elif cmd.has_any("remember", "memorize") or cmd.contains("note that") or cmd.contains("keep in mind") or cmd.contains("don't forget"):
            sub = "store"
            if not cmd.is_question:
                score = min(1.0, score + 0.1)

        # ── Recall (secondary keywords) ───────────────────────────────
        elif cmd.has_any("recall") or cmd.contains("do you know"):
            sub = "recall"
            score = min(1.0, score + 0.2)

        # ── Forget ────────────────────────────────────────────────────
        elif cmd.has_any("forget"):
            sub = "forget"
            score = min(1.0, score + 0.1)

        return IntentResult(INTENT_MEMORY, score, matched, sub_intent=sub)

    # ── Helpers ───────────────────────────────────────────────

    def _keyword_score(
        self,
        cmd: ParsedCommand,
        keyword_map: Dict[str, float],
    ) -> Tuple[List[str], float]:
        """
        Score a command against a keyword map.
        Returns (matched_keywords, confidence_score).
        Uses diminishing returns for multiple matches.
        """
        matched = []
        total_score = 0.0

        for keyword, weight in keyword_map.items():
            if keyword in cmd.normalized:
                matched.append(keyword)
                total_score += weight

        if not matched:
            return [], 0.0

        # Diminishing returns: more matches don't linearly increase score
        # First match is full weight, subsequent matches contribute less
        scores = sorted(
            [keyword_map[k] for k in matched], reverse=True
        )
        confidence = scores[0]
        for i, s in enumerate(scores[1:], 1):
            confidence += s * (0.5 ** i)

        confidence = min(1.0, confidence)
        return matched, round(confidence, 3)

    def _extract_system_sub(self, cmd: ParsedCommand) -> Optional[str]:
        if cmd.has_any("volume", "mute", "unmute", "louder", "quieter"):
            return "volume"
        elif cmd.has_any("brightness", "dim"):
            return "brightness"
        elif cmd.has_any("wifi"):
            return "wifi"
        elif cmd.has_any("bluetooth"):
            return "bluetooth"
        elif cmd.has_any("shutdown", "restart", "reboot"):
            return "power"
        elif cmd.has_any("sleep"):
            return "sleep"
        elif cmd.has_any("lock", "lock screen", "lock computer"):
            return "lock"
        elif cmd.has_any("dark mode", "darkmode"):
            return "display"
        return None


__all__ = [
    "IntentDetector", "IntentResult",
    "INTENT_APP_CONTROL", "INTENT_SYSTEM_CONTROL", "INTENT_MEDIA_CONTROL",
    "INTENT_WEB_SEARCH", "INTENT_UTILITY", "INTENT_QUESTION_ANSWER",
    "INTENT_MEMORY", "INTENT_UNKNOWN", "ALL_INTENTS",
    "CONFIDENCE_HIGH", "CONFIDENCE_MEDIUM", "CONFIDENCE_LOW",
]
