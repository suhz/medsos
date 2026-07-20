"""SQLAlchemy 2.0 models: Account, Post, Reply, Event.

Reply nodes are unified: one table holds both inbound comments and outbound
replies we've published, distinguished by `direction` and `status`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32))
    platform_user_id: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(128))
    access_token: Mapped[str] = mapped_column(Text)  # encrypted
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|expired|revoked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                default=lambda: datetime.now(),
                                                onupdate=lambda: datetime.now())

    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_accounts_platform_user"),)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(index=True)
    platform_media_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    media_urls: Mapped[str] = mapped_column(Text, default="[]")  # JSON string
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|publishing|published|failed
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                default=lambda: datetime.now(),
                                                onupdate=lambda: datetime.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("account_id", "platform_media_id", name="uq_posts_account_media"),)


class Reply(Base):
    __tablename__ = "replies"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(index=True)
    platform_id: Mapped[str] = mapped_column(String(64))
    parent_platform_id: Mapped[str] = mapped_column(String(64))
    root_platform_post_id: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(8))  # inbound|outbound
    kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # replies|mentions
    author_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    author_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    permalink: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shortcode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    skip_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "platform_id", name="uq_replies_account_platform_id"),
        Index("ix_replies_account_status_created", "account_id", "status", "created_at"),
    )


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[Optional[int]] = mapped_column(index=True, nullable=True)
    platform_event_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))  # replies|mentions|publish|delete
    raw: Mapped[str] = mapped_column(Text, default="{}")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now())

    __table_args__ = (UniqueConstraint("platform_event_id", name="uq_events_platform_event_id"),)


class OauthState(Base):
    __tablename__ = "oauth_states"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))