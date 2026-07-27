from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from research_memory.contracts import (
    ResearchProfile,
    TaxonomyEvidence,
)
from research_memory.generated.taxonomy_catalog import AssignmentRole
from research_memory.services.taxonomy_catalog import TaxonomyCatalog


class ClassifierModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArticleContext(ClassifierModel):
    article_id: int
    title: str
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    why_saved: str = ""
    user_summary: str = ""


class TaxonomyCandidate(ClassifierModel):
    node_id: str
    role: AssignmentRole
    confidence: float = Field(ge=0, le=1)
    evidence: list[TaxonomyEvidence] = Field(default_factory=list)


class TaxonomyClassifier(Protocol):
    """Classifier boundary reserved for Phase 4.

    Phase 1 defines the contract but intentionally provides no automated
    classifier implementation.
    """

    version: str

    def classify(
        self,
        article: ArticleContext,
        profile: ResearchProfile,
        catalog: TaxonomyCatalog,
    ) -> list[TaxonomyCandidate]: ...
