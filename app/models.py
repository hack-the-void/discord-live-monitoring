from __future__ import annotations

from pydantic import BaseModel, Field


class FeedItem(BaseModel):
    title: str = Field(default="")
    link: str = Field(default="")
    summary: str = Field(default="")
    published_at: str = Field(default="")
    source: str = Field(default="")


class CyberFeedItem(BaseModel):
    entry_id: str = Field(default="")
    title: str = Field(default="")
    link: str = Field(default="")
    summary: str = Field(default="")
    published_at: str = Field(default="")
    source: str = Field(default="")
    cve_ids: list[str] = Field(default_factory=list)


class ShortlistOutput(BaseModel):
    selected_indices: list[int] = Field(
        default_factory=list,
        description="Indices des articles à garder, par ordre d'importance.",
    )