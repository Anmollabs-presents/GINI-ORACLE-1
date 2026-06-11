# ============================================================
# GINI-ORACLE-1 — Conversation Memory System
# core/memory.py
# ============================================================
"""
Manages per-user conversation history, session context, and persistent memories.
Backed by SQLite in Phase 2 for profile facts, preferences, and session recall.

Features:
- Persistent session and turn storage
- Per-user memory facts and preferences
- Sliding window (last N turns)
- Emotion history tracking
- Clear / reset support
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional

UTC = timezone.utc

def _now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(UTC)

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    func,
    or_,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)
Base = declarative_base()

# Max turns kept per session (sliding window)
DEFAULT_WINDOW_SIZE = 20

MEMORY_CATEGORIES = {
    "personal": "Personal Memory",
    "project": "Project Memory",
    "preference": "Preferences",
    "preferences": "Preferences",
    "task": "Tasks",
    "tasks": "Tasks",
    "fact": "Facts",
    "facts": "Facts",
}


def normalize_category(name: str) -> str:
    value = (name or "").strip().lower()
    return MEMORY_CATEGORIES.get(value, MEMORY_CATEGORIES["facts"])


class DBSessionRecord(Base):
    __tablename__ = "sessions"

    session_id = Column(String(128), primary_key=True)
    user_id = Column(String(128), nullable=False, index=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    last_active = Column(DateTime, default=_now, nullable=False)
    turns = relationship(
        "DBTurnRecord",
        cascade="all, delete-orphan",
        back_populates="session",
        order_by="DBTurnRecord.timestamp",
    )


class DBTurnRecord(Base):
    __tablename__ = "turns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String(128),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    emotion = Column(String(32), nullable=True)
    timestamp = Column(DateTime, default=_now, nullable=False)
    session = relationship("DBSessionRecord", back_populates="turns")


class MemoryFactRecord(Base):
    __tablename__ = "memory_facts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, index=True)
    topic = Column(String(128), nullable=False, index=True)
    category = Column(String(64), nullable=False, default="Facts", server_default="Facts", index=True)
    value = Column(Text, nullable=False)
    added_at = Column(DateTime, default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "topic", name="uix_user_topic"),
    )


@dataclass
class Turn:
    """A single conversation turn (user + assistant exchange)."""
    role: str
    content: str
    emotion: Optional[str] = None
    timestamp: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "emotion": self.emotion,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Session:
    """A user's full conversation session."""
    user_id: str
    session_id: str
    turns: List[Turn] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    last_active: datetime = field(default_factory=_now)
    metadata: Dict = field(default_factory=dict)

    def add_turn(self, role: str, content: str, emotion: Optional[str] = None) -> None:
        """Append a new turn to the session."""
        self.turns.append(Turn(role=role, content=content, emotion=emotion))
        self.last_active = _now()

    def get_history(self, window: int = DEFAULT_WINDOW_SIZE) -> List[dict]:
        """Return last N turns as list of dicts (for LLM context)."""
        return [t.to_dict() for t in self.turns[-window:]]

    def get_emotion_trend(self) -> str:
        """
        Returns dominant emotion over last 5 turns.
        Useful for Gini to adapt tone over time.
        """
        recent = [t.emotion for t in self.turns[-5:] if t.emotion]
        if not recent:
            return "neutral"
        return max(set(recent), key=recent.count)

    def clear(self) -> None:
        """Reset conversation history."""
        self.turns.clear()
        log.info(f"Session cleared: [{self.session_id}]")


class MemoryManager:
    """
    Manages all user sessions and persistent memory facts.
    """

    def __init__(self, window_size: int = DEFAULT_WINDOW_SIZE, database_url: Optional[str] = None):
        self.window_size = window_size
        self.database_url = database_url or settings.database_url

        engine_kwargs = {}
        if self.database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}

        self._engine = create_engine(self.database_url, **engine_kwargs)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)
        self._ensure_memory_category_column()
        self._session_cache: Dict[str, Session] = {}

        log.info(
            f"🧠 MemoryManager initialized | DB={self.database_url} | Window size: {window_size}"
        )

    def _session(self):
        return self._Session()

    def _load_session(self, db_session: DBSessionRecord) -> Session:
        return Session(
            user_id=db_session.user_id,
            session_id=db_session.session_id,
            turns=[
                Turn(
                    role=turn.role,
                    content=turn.content,
                    emotion=turn.emotion,
                    timestamp=turn.timestamp,
                )
                for turn in sorted(db_session.turns, key=lambda t: (t.timestamp, t.id))
            ],
            created_at=db_session.created_at,
            last_active=db_session.last_active,
            metadata={},
        )

    def get_or_create_session(self, user_id: str, session_id: Optional[str] = None) -> Session:
        """
        Get existing session or create a new one.
        If session_id is None, creates a new session automatically.
        """
        sid = session_id or f"{user_id}_{_now().strftime('%Y%m%d%H%M%S%f')}"

        if sid in self._session_cache:
            return self._session_cache[sid]

        with self._session() as db:
            db_session = db.get(DBSessionRecord, sid)
            if db_session is None:
                db_session = DBSessionRecord(session_id=sid, user_id=user_id)
                db.add(db_session)
                db.commit()
                db.refresh(db_session)
                log.debug(f"New session created: [{sid}] for user [{user_id}]")
            session = self._load_session(db_session)
            self._session_cache[sid] = session
            return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID. Returns None if not found."""
        if session_id in self._session_cache:
            return self._session_cache[session_id]

        with self._session() as db:
            db_session = db.get(DBSessionRecord, session_id)
            if not db_session:
                return None
            session = self._load_session(db_session)
            self._session_cache[session_id] = session
            return session

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        emotion: Optional[str] = None,
    ) -> None:
        """Append a turn to the given session."""
        with self._session() as db:
            db_session = db.get(DBSessionRecord, session_id)
            if not db_session:
                log.warning(f"add_turn: session [{session_id}] not found")
                return
            turn = DBTurnRecord(
                session_id=session_id,
                role=role,
                content=content,
                emotion=emotion,
                timestamp=_now(),
            )
            db_session.last_active = _now()
            db.add(turn)
            db.commit()

        if session_id in self._session_cache:
            self._session_cache[session_id].add_turn(role=role, content=content, emotion=emotion)

    def get_history(self, session_id: str) -> List[dict]:
        """Get conversation history for a session."""
        with self._session() as db:
            session_exists = db.get(DBSessionRecord, session_id)
            if not session_exists:
                return []
            turns = (
                db.query(DBTurnRecord)
                .filter_by(session_id=session_id)
                .order_by(DBTurnRecord.timestamp.desc(), DBTurnRecord.id.desc())
                .limit(self.window_size)
                .all()
            )
            return [
                {
                    "role": t.role,
                    "content": t.content,
                    "emotion": t.emotion,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in reversed(turns)
            ]

    def get_emotion_trend(self, session_id: str) -> str:
        """Get the dominant emotion for a session."""
        with self._session() as db:
            emotions = [
                row[0]
                for row in (
                    db.query(DBTurnRecord.emotion)
                    .filter_by(session_id=session_id)
                    .order_by(DBTurnRecord.timestamp.desc(), DBTurnRecord.id.desc())
                    .limit(5)
                    .all()
                )
                if row[0]
            ]
            if not emotions:
                return "neutral"
            return max(set(emotions), key=emotions.count)

    def clear_session(self, session_id: str) -> None:
        """Clear history for a session."""
        with self._session() as db:
            db.query(DBTurnRecord).filter_by(session_id=session_id).delete()
            session_obj = db.get(DBSessionRecord, session_id)
            if session_obj:
                session_obj.last_active = _now()
            db.commit()

        if session_id in self._session_cache:
            self._session_cache[session_id].clear()

    def delete_session(self, session_id: str) -> None:
        """Delete a session entirely."""
        with self._session() as db:
            db.query(DBTurnRecord).filter_by(session_id=session_id).delete()
            session_obj = db.get(DBSessionRecord, session_id)
            if session_obj:
                db.delete(session_obj)
            db.commit()
            log.info(f"Session deleted: [{session_id}]")

        if session_id in self._session_cache:
            self._session_cache.pop(session_id, None)

    def get_user_sessions(self, user_id: str) -> List[str]:
        """List all session IDs for a user."""
        with self._session() as db:
            results = (
                db.query(DBSessionRecord.session_id)
                .filter_by(user_id=user_id)
                .order_by(DBSessionRecord.last_active.desc())
                .all()
            )
            return [row[0] for row in results]

    def _ensure_memory_category_column(self) -> None:
        """Ensure the persistent memory table has a category column."""
        inspector = inspect(self._engine)
        if "memory_facts" not in inspector.get_table_names():
            return
        columns = [col["name"] for col in inspector.get_columns("memory_facts")]
        if "category" not in columns:
            with self._engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE memory_facts ADD COLUMN category VARCHAR(64) NOT NULL DEFAULT 'Facts'"
                    )
                )
                conn.commit()

    def _infer_category(self, topic: str, value: str | None = None) -> str:
        normalized_topic = (topic or "").strip().lower()
        if normalized_topic in {"name", "first name", "last name", "me", "fullname", "full name"}:
            return MEMORY_CATEGORIES["personal"]
        if normalized_topic in {"project", "project name", "building", "working on", "app"}:
            return MEMORY_CATEGORIES["project"]
        if "color" in normalized_topic or "colour" in normalized_topic or normalized_topic in {"preference", "preferences", "like", "love", "hate"}:
            return MEMORY_CATEGORIES["preference"]
        if normalized_topic in {"task", "todo", "reminder", "reminders", "due", "deadline"}:
            return MEMORY_CATEGORIES["tasks"]
        if normalized_topic in {"note", "fact", "facts", "idea", "information"}:
            return MEMORY_CATEGORIES["facts"]
        if value:
            value_lower = value.lower()
            if "project" in value_lower or "gini" in value_lower or "building" in value_lower:
                return MEMORY_CATEGORIES["project"]
            if "color" in value_lower or "colour" in value_lower or "like" in value_lower:
                return MEMORY_CATEGORIES["preference"]
        return MEMORY_CATEGORIES["facts"]

    def remember_fact(self, user_id: str, topic: str, value: str, category: Optional[str] = None) -> str:
        """Store or update a persistent memory fact for a user."""
        if not topic or not value:
            return ""
        category_name = normalize_category(category) if category else self._infer_category(topic, value)
        with self._session() as db:
            fact = (
                db.query(MemoryFactRecord)
                .filter_by(user_id=user_id, topic=topic)
                .one_or_none()
            )
            if fact:
                fact.value = value
                fact.category = category_name
                fact.added_at = _now()
            else:
                fact = MemoryFactRecord(
                    user_id=user_id,
                    topic=topic,
                    category=category_name,
                    value=value,
                )
                db.add(fact)
            db.commit()
        return value

    def recall_fact(self, user_id: str, topic: Optional[str] = None, category: Optional[str] = None):
        """Retrieve memory facts for a user, optionally by topic or category."""
        with self._session() as db:
            query = db.query(MemoryFactRecord).filter_by(user_id=user_id)
            if category:
                query = query.filter(MemoryFactRecord.category == normalize_category(category))
            if topic:
                like_expr = f"%{topic}%"
                query = query.filter(
                    or_(
                        MemoryFactRecord.topic.ilike(like_expr),
                        MemoryFactRecord.value.ilike(like_expr),
                    )
                )
            facts = query.order_by(MemoryFactRecord.added_at.desc()).all()

        if not facts:
            return None
        if topic and len(facts) == 1:
            return facts[0].value
        return {fact.topic: fact.value for fact in facts}

    def search_facts(self, user_id: str, query: str):
        """Search memory facts by topic or value for a user."""
        return self.recall_fact(user_id, topic=query)

    def forget_fact(self, user_id: str, topic: Optional[str]) -> int:
        """Remove memory facts matching the topic for a user."""
        if not topic:
            return 0
        with self._session() as db:
            like_expr = f"%{topic}%"
            deleted = (
                db.query(MemoryFactRecord)
                .filter_by(user_id=user_id)
                .filter(
                    or_(
                        MemoryFactRecord.topic.ilike(like_expr),
                        MemoryFactRecord.value.ilike(like_expr),
                    )
                )
                .delete(synchronize_session=False)
            )
            db.commit()
        return deleted

    def get_active_topic(self, session_id: str) -> Optional[str]:
        """
        Scan the last few turns of the session history to identify the active topic.
        Looks for the most recent noun/subject discussed.
        """
        history = self.get_history(session_id)
        if not history:
            return None
        
        # Look at turns starting from the most recent
        for turn in reversed(history):
            content = turn.get("content", "").lower()
            words = [w.strip("?,.!:;()\"'") for w in content.split()]
            stop_words = {
                "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
                "at", "from", "by", "for", "with", "about", "against", "between",
                "into", "through", "during", "before", "after", "above", "below",
                "to", "in", "on", "of", "off", "over", "under", "again", "further",
                "once", "here", "there", "where", "why", "how", "all", "any", "both",
                "each", "few", "more", "most", "other", "some", "such", "no", "nor",
                "not", "only", "own", "same", "so", "than", "too", "very", "can",
                "will", "just", "should", "now", "my", "your", "his", "her", "its",
                "their", "our", "me", "you", "him", "them", "us", "i", "we", "he",
                "she", "it", "they", "what", "which", "who", "whom", "this", "that",
                "these", "those", "am", "is", "are", "was", "were", "be", "been",
                "being", "have", "has", "had", "having", "do", "does", "did", "doing",
                "would", "could", "should", "explain", "describe", "define", "tell",
                "what's", "whats", "who's", "whos", "please", "know", "remember"
            }
            # Find first word that is not a stop word and has length > 2
            for word in words:
                if len(word) > 2 and word not in stop_words:
                    return word
        return None

    def get_relevant_memories(self, user_id: str, query: str, active_topic: Optional[str] = None, limit: int = 5) -> Dict[str, str]:
        """
        Retrieve persistent memories for a user and score them against the query and active topic
        using keyword overlap. Returns a dictionary of relevant memories grouped by category.
        """
        with self._session() as db:
            facts = db.query(MemoryFactRecord).filter_by(user_id=user_id).all()
        
        if not facts:
            return {}

        stop_words = {
            "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
            "at", "from", "by", "for", "with", "about", "against", "between",
            "into", "through", "during", "before", "after", "above", "below",
            "to", "in", "on", "of", "off", "over", "under", "again", "further",
            "once", "here", "there", "where", "why", "how", "all", "any", "both",
            "each", "few", "more", "most", "other", "some", "such", "no", "nor",
            "not", "only", "own", "same", "so", "than", "too", "very", "can",
            "will", "just", "should", "now", "my", "your", "his", "her", "its",
            "their", "our", "me", "you", "him", "them", "us", "i", "we", "he",
            "she", "it", "they", "what", "which", "who", "whom", "this", "that",
            "these", "those", "am", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "having", "do", "does", "did", "doing",
            "would", "could", "should", "explain", "describe", "define", "tell",
            "what's", "whats", "who's", "whos", "please", "know", "remember"
        }
        
        def tokenize(text_str: str) -> set:
            words = text_str.lower().split()
            cleaned = set()
            for w in words:
                w_clean = w.strip("?,.!:;()\"'")
                if len(w_clean) > 2 and w_clean not in stop_words:
                    cleaned.add(w_clean)
            return cleaned

        query_keywords = tokenize(query)
        topic_keywords = tokenize(active_topic) if active_topic else set()
        all_search_keywords = query_keywords.union(topic_keywords)

        scored_facts = []
        for fact in facts:
            fact_topic_words = tokenize(fact.topic)
            fact_value_words = tokenize(fact.value)
            
            score = 0
            for kw in all_search_keywords:
                if kw in fact_topic_words:
                    score += 3
                if kw in fact_value_words:
                    score += 1

            query_lower = query.lower()
            if "name" in query_lower or "who" in query_lower:
                if fact.topic.lower() in ("name", "profile"):
                    score += 2
            if "project" in query_lower or "building" in query_lower or "working" in query_lower:
                if fact.topic.lower() == "project":
                    score += 2
            if "color" in query_lower or "colour" in query_lower or "favorite" in query_lower:
                if "color" in fact.topic.lower() or "colour" in fact.topic.lower():
                    score += 2

            scored_facts.append((score, fact))

        # Sort by score descending
        scored_facts.sort(key=lambda x: x[0], reverse=True)
        
        category_map = {
            "Personal Memory": "personal",
            "Project Memory": "project",
            "Preferences": "preferences",
            "Tasks": "tasks",
            "Facts": "facts"
        }

        grouped = {}
        count = 0
        for score, fact in scored_facts:
            if score <= 0:
                continue
            cat_key = category_map.get(fact.category, "facts")
            if cat_key not in grouped:
                grouped[cat_key] = []
            grouped[cat_key].append(f"{fact.topic}: {fact.value}")
            count += 1
            if count >= limit:
                break
                
        return {cat: "\n".join(lines) for cat, lines in grouped.items()}

    @property
    def total_sessions(self) -> int:
        with self._session() as db:
            return db.query(func.count(DBSessionRecord.session_id)).scalar() or 0

    @property
    def total_users(self) -> int:
        with self._session() as db:
            return db.query(func.count(func.distinct(DBSessionRecord.user_id))).scalar() or 0


__all__ = ["MemoryManager", "Session", "Turn"]
