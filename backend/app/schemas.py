from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class Sentence(BaseModel):
    text: str
    kind: Literal["paper", "authors_claim", "background"]
    source: Literal["text", "pdf", "image"] = "text"
    span_ids: list[str] = []
    quote: Optional[str] = None
    page: Optional[int] = None

    @field_validator("span_ids", mode="before")
    @classmethod
    def clean_ids(cls, v):
        return [str(x).split()[0] for x in (v or []) if str(x).strip()]


class Explanation(BaseModel):
    sentences: list[Sentence]