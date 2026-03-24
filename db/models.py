import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class QuestionType(str, enum.Enum):
    input = "input"
    choice = "choice"


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)  # Telegram user ID
    username = Column(Text, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    progress = relationship("Progress", back_populates="user", cascade="all, delete-orphan")
    answers = relationship("Answer", back_populates="user", cascade="all, delete-orphan")


class Word(Base):
    __tablename__ = "words"

    id = Column(Integer, primary_key=True, autoincrement=True)
    display = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)
    question_type = Column(Enum(QuestionType), nullable=False)
    rule = Column(Text, nullable=False)
    task_number = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    explanation = relationship("Explanation", back_populates="word", uselist=False, cascade="all, delete-orphan")
    progress = relationship("Progress", back_populates="word", cascade="all, delete-orphan")
    answers = relationship("Answer", back_populates="word", cascade="all, delete-orphan")


class Explanation(Base):
    __tablename__ = "explanations"

    word_id = Column(Integer, ForeignKey("words.id"), primary_key=True)
    text = Column(Text, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    word = relationship("Word", back_populates="explanation")


class Progress(Base):
    __tablename__ = "progress"

    user_id = Column(BigInteger, ForeignKey("users.id"), primary_key=True)
    word_id = Column(Integer, ForeignKey("words.id"), primary_key=True)
    interval = Column(Integer, default=0, nullable=False)
    repetitions = Column(Integer, default=0, nullable=False)
    ef = Column(Float, default=2.5, nullable=False)
    next_review = Column(Date, nullable=False)

    user = relationship("User", back_populates="progress")
    word = relationship("Word", back_populates="progress")

    __table_args__ = (
        Index("ix_progress_user_next_review", "user_id", "next_review"),
    )


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    word_id = Column(Integer, ForeignKey("words.id"), nullable=False)
    is_correct = Column(Boolean, nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="answers")
    word = relationship("Word", back_populates="answers")

    __table_args__ = (
        Index("ix_answers_user_ts", "user_id", "ts"),
    )
