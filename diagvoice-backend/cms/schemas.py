from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Period(BaseModel):
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    label: str | None = None

    model_config = {"populate_by_name": True}


class UiCardConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    displayTitle: str | None = None
    subtitle: str | None = None
    footnote: str | None = None
    badge: str | None = None
    period: Period | None = None


class UiProfileCreate(BaseModel):
    key: str
    label: str
    cards: list[UiCardConfig]


class UiProfileUpdate(BaseModel):
    label: str | None = None
    cards: list[UiCardConfig] | None = None


class UiProfileOut(BaseModel):
    id: str
    key: str
    label: str
    cards: list[dict[str, Any]]


class PageCreate(BaseModel):
    slug: str
    title: str
    description: str | None = None
    published: bool = False
    sortOrder: int = 0
    profileKey: str
    layout: str = "demo_default"


class PageUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    published: bool | None = None
    sortOrder: int | None = None
    profileKey: str | None = None
    layout: str | None = None


class PageOut(BaseModel):
    id: str
    slug: str
    title: str
    description: str | None
    published: bool
    sortOrder: int
    profileKey: str
    layout: str
    updatedAt: datetime | None = None


class PageWithProfileOut(PageOut):
    profile: UiProfileOut | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMe(BaseModel):
    email: str
    role: str
