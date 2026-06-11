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
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)
Base = declarative_base()

# Max turns kept per session (sliding window)
DEFAULT_WINDOW_SIZE = 20


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

    def remember_fact(self, user_id: str, topic: str, value: str) -> str:
        """Store or update a memory fact for a user."""
        if not topic or not value:
            return ""
        with self._session() as db:
            fact = (
                db.query(MemoryFactRecord)
                .filter_by(user_id=user_id, topic=topic)
                .one_or_none()
            )
            if fact:
                fact.value = value
                fact.added_at = _now()
            else:
                fact = MemoryFactRecord(user_id=user_id, topic=topic, value=value)
                db.add(fact)
            db.commit()
        return value

    def recall_fact(self, user_id: str, topic: Optional[str] = None):
        """Retrieve memory facts for a user."""
        with self._session() as db:
            query = db.query(MemoryFactRecord).filter_by(user_id=user_id)
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
        if topic:
            if len(facts) == 1:
                return facts[0].value
            return {fact.topic: fact.value for fact in facts}
        return {fact.topic: fact.value for fact in facts}

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

    @property
    def total_sessions(self) -> int:
        with self._session() as db:
            return db.query(func.count(DBSessionRecord.session_id)).scalar() or 0

    @property
    def total_users(self) -> int:
        with self._session() as db:
            return db.query(func.count(func.distinct(DBSessionRecord.user_id))).scalar() or 0


__all__ = ["MemoryManager", "Session", "Turn"]
