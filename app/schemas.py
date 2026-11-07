from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def trim_message(cls, value):
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value.strip()


class Source(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: list[Source] = Field(default_factory=list)
    outcome: Literal["answered", "needs_clarification", "escalated", "escalation_pending"]
    ticket_id: str | None = None


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["account", "docs", "human", "resolved", "other", "greeting",
                    "smalltalk", "acknowledgement", "confirmation", "decline", "repeat", "simplify", "restricted", "ticket_status", "pause", "account_status", "next_steps"]
    new_issue: bool
    unresolved: bool
    documentation_question: str | None = Field(default=None, max_length=2000)
    followup: Literal["advance", "clarify", "completed", "failed"] = "advance"
    step_number: int | None = Field(default=None, ge=1, le=30)


class DocAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1, max_length=6000)
    source_ids: list[int] = Field(max_length=5)
    supported: bool


class ReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1200)


class ProgressDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["advance", "clarify", "completed", "failed"]
    step_number: int | None = Field(ge=1, le=30)

