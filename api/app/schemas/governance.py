import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Policy(Strict):
    run_tokens: int = Field(default=120000, ge=1000, le=2000000)
    step_tokens: int = Field(default=32000, ge=1000, le=200000)
    output_tokens: int = Field(default=1500, ge=64, le=8000)
    attempts_per_step: int = Field(default=3, ge=1, le=5)
    run_budget_microusd: int = Field(default=0, ge=0, le=1000000000)
    step_budget_microusd: int = Field(default=0, ge=0, le=1000000000)
    shared_memory: bool = True
    trace_content: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if self.output_tokens >= self.step_tokens or self.step_tokens > self.run_tokens:
            raise ValueError("Use saída < limite da etapa ≤ limite do planejamento")
        if self.step_budget_microusd > self.run_budget_microusd:
            raise ValueError("O orçamento da etapa não pode exceder o do planejamento")
        return self


class SecretCreate(Strict):
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["api_key", "database_password", "ssh_key"]
    value: SecretStr = Field(min_length=1, max_length=16000)
    allowed_roles: list[Literal["product", "architecture", "implementation", "review"]] = Field(min_length=1, max_length=4)
    allowed_tools: list[Literal["api.read", "database.read", "production.deploy"]] = Field(min_length=1, max_length=3)


class ActionPayload(Strict):
    resource: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=120)
    estimated_microusd: int = Field(ge=0, le=1000000000)


class ApprovalCreate(Strict):
    action: Literal["production_deploy", "paid_resource"]
    target: str = Field(min_length=2, max_length=250)
    payload: ActionPayload
    rationale: str = Field(min_length=10, max_length=1000)


class ApprovalDecision(Strict):
    decision: Literal["approved", "rejected"]
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    password: SecretStr = Field(min_length=1, max_length=100)


class NoteCreate(Strict):
    title: str = Field(min_length=2, max_length=160)
    content: str = Field(min_length=5, max_length=6000)
    kind: Literal["fact", "decision", "artifact"] = "fact"


class EdgeCreate(Strict):
    source_id: uuid.UUID
    target_id: uuid.UUID
    relation: Literal["depends_on", "supports", "contradicts", "relates_to"]


class TemplateStep(Strict):
    key: Literal["product", "architecture", "implementation", "review"]
    title: str = Field(min_length=2, max_length=80)
    instruction: str = Field(min_length=20, max_length=2000)


class TemplateCreate(Strict):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    steps: list[TemplateStep] = Field(min_length=4, max_length=4)
    source_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def ordered_roles(self):
        if [step.key for step in self.steps] != ["product", "architecture", "implementation", "review"]:
            raise ValueError("Informe os quatro papéis na ordem produto, arquitetura, implementação e revisão")
        return self


class RatingCreate(Strict):
    score: int = Field(ge=1, le=5)
