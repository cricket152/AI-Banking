"""资金写入仅提供给已认证、同源 CSRF 和明确授权的应用 API。"""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_banking.banking.reports import Reports
from ai_banking.banking.service import MAX_MINOR

Identifier = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Amount = Annotated[int, Field(ge=1, le=MAX_MINOR)]
Password = Annotated[str, Field(min_length=1, max_length=128, repr=False)]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class TaskBody(StrictBody):
    request_id: str = Field(min_length=32, max_length=36)

    @field_validator("request_id")
    @classmethod
    def normalize_uuid(cls, value):
        return UUID(value).hex


class PayeeBody(StrictBody):
    name: str = Field(min_length=1, max_length=64)
    account_id: Identifier
    password: Password


class DemoPayeesBody(StrictBody):
    password: Password


class CardApplyBody(StrictBody):
    account_id: Identifier
    kind: Literal["debit", "credit"] = "debit"
    daily_limit_minor: int = Field(default=500000, ge=0, le=10_000_000)
    password: Password


class CardLimitBody(StrictBody):
    daily_limit_minor: int = Field(ge=0, le=10_000_000)
    password: Password


class CardStatusBody(StrictBody):
    status: Literal["active", "frozen", "lost"]
    password: Password


class ScenarioBody(StrictBody):
    kind: Literal["birthday", "anniversary", "custom"]
    title: str = Field(min_length=1, max_length=40)
    occasion_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    budget_minor: Amount
    source_id: Identifier
    payee_id: Identifier


class PayeeNoteBody(DemoPayeesBody):
    note: str = Field(max_length=64)


class WorkflowPreviewBody(StrictBody):
    source_id: Identifier
    payee_id: Identifier
    amount_minor: Amount
    subscription_ids: list[Identifier] = Field(min_length=1, max_length=5)


class WorkflowBody(WorkflowPreviewBody, TaskBody):
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    acknowledged: bool

    @field_validator("acknowledged")
    @classmethod
    def explicit_plan_selection(cls, value):
        if not value:
            raise ValueError("必须核对方案")
        return value


class GrantBody(TaskBody):
    source_id: Identifier
    currency: Literal["CNY"]
    payee_ids: list[Identifier] = Field(max_length=50)
    allowed_operations: list[Literal["transfer", "cancel_subscription"]] = Field(
        min_length=1, max_length=2
    )
    subscription_ids: list[Identifier] = Field(max_length=50)
    limit_minor: int = Field(ge=0, le=MAX_MINOR)
    single_minor: int = Field(ge=0, le=MAX_MINOR)
    minimum_minor: int = Field(ge=0, le=MAX_MINOR)
    expires_at: float = Field(gt=0)
    password: Password


class PrepareBody(StrictBody):
    task_id: Identifier
    step_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    source_id: Identifier
    currency: Literal["CNY"]
    mode: Literal["HUMAN_APPROVAL", "PREAUTHORIZED"]
    grant_id: Identifier | None = None
    confirmation_seconds: int = Field(default=300, ge=30, le=3600)


class TransferBody(PrepareBody):
    payee_id: Identifier
    amount_minor: Amount


class CancelBody(PrepareBody):
    subscription_id: Identifier


class DecisionBody(StrictBody):
    decision: Literal["approve", "reject"]
    challenge: str = Field(min_length=32, max_length=128, repr=False)
    parameters_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class SubscriptionRegistrationBody(StrictBody):
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    acknowledged: Literal[True]

    @field_validator("acknowledged", mode="before")
    @classmethod
    def explicit_acknowledgement(cls, value):
        if value is not True:
            raise ValueError("必须明确核对并确认登记")
        return value


def router(bank, auth, identity, mutation):
    routes = APIRouter(prefix="/api/bank")
    reports = Reports(bank)

    def reauth(request, context, password):
        auth.reauthenticate(context, password, request.client.host if request.client else "unknown")

    @routes.get("/payees")
    def payees(context=Depends(identity)):
        return {"payees": bank.payees(context)}

    @routes.post("/payees", dependencies=[Depends(mutation)])
    def add_payee(body: PayeeBody, request: Request, context=Depends(identity)):
        reauth(request, context, body.password)
        return bank.add_payee(context, body.name, body.account_id)

    @routes.post("/payees/demo", dependencies=[Depends(mutation)])
    def demo_payees(body: DemoPayeesBody, request: Request, context=Depends(identity)):
        from ai_banking.banking.contacts import load_demo_contacts

        reauth(request, context, body.password)
        return load_demo_contacts(bank, context)

    @routes.post("/payees/{payee_id}/note", dependencies=[Depends(mutation)])
    def payee_note(payee_id: str, body: PayeeNoteBody, request: Request, context=Depends(identity)):
        from ai_banking.banking.contacts import set_note

        reauth(request, context, body.password)
        return set_note(bank, context, payee_id, body.note)

    @routes.get("/cards")
    def cards(context=Depends(identity)):
        from ai_banking.banking.cards import list_cards

        return list_cards(bank, context)

    @routes.post("/cards/apply", dependencies=[Depends(mutation)])
    def apply_card(body: CardApplyBody, request: Request, context=Depends(identity)):
        from ai_banking.banking.cards import apply_card as create

        reauth(request, context, body.password)
        return create(bank, context, body.account_id, body.kind, body.daily_limit_minor)

    @routes.post("/cards/{card_id}/limit", dependencies=[Depends(mutation)])
    def card_limit(card_id: str, body: CardLimitBody, request: Request, context=Depends(identity)):
        from ai_banking.banking.cards import update_limit

        reauth(request, context, body.password)
        return update_limit(bank, context, card_id, body.daily_limit_minor)

    @routes.post("/cards/{card_id}/status", dependencies=[Depends(mutation)])
    def card_status(
        card_id: str, body: CardStatusBody, request: Request, context=Depends(identity)
    ):
        from ai_banking.banking.cards import set_status

        reauth(request, context, body.password)
        return set_status(bank, context, card_id, body.status)

    @routes.get("/scenarios")
    def scenarios(context=Depends(identity)):
        from ai_banking.banking.scenarios import list_scenarios

        return list_scenarios(bank, context)

    @routes.post("/scenarios", dependencies=[Depends(mutation)])
    def create_scenario(body: ScenarioBody, context=Depends(identity)):
        from ai_banking.banking.scenarios import create_scenario as create

        return create(bank, context, body.model_dump())

    @routes.post("/scenarios/{scenario_id}/order", dependencies=[Depends(mutation)])
    def order_scenario(scenario_id: str, body: StrictBody, context=Depends(identity)):
        from ai_banking.banking.scenarios import order_scenario as order

        return order(bank, context, scenario_id)

    @routes.post("/scenarios/{scenario_id}/cancel", dependencies=[Depends(mutation)])
    def cancel_scenario(scenario_id: str, body: StrictBody, context=Depends(identity)):
        from ai_banking.banking.scenarios import cancel_scenario as cancel

        return cancel(bank, context, scenario_id)

    @routes.post("/tasks", dependencies=[Depends(mutation)])
    def create_task(body: TaskBody, context=Depends(identity)):
        return bank.task(context, body.request_id)

    @routes.post("/plans/preview", dependencies=[Depends(mutation)])
    def plan_preview(body: WorkflowPreviewBody, context=Depends(identity)):
        from ai_banking.banking.workflows import preview_plan

        return preview_plan(bank, context, body.model_dump())

    @routes.post("/plans", dependencies=[Depends(mutation)])
    def select_plan(body: WorkflowBody, context=Depends(identity)):
        from ai_banking.banking.workflows import create_plan

        return create_plan(bank, context, body.model_dump())

    @routes.get("/tasks/{task_id}")
    def task(task_id: str, context=Depends(identity)):
        return bank.checkpoint(context, task_id)

    @routes.get("/grants")
    def grants(context=Depends(identity)):
        return {"grants": bank.grants(context)}

    @routes.post("/grants", dependencies=[Depends(mutation)])
    def grant(body: GrantBody, request: Request, context=Depends(identity)):
        reauth(request, context, body.password)
        return bank.create_grant(context, body.model_dump(exclude={"password"}))

    @routes.post("/grants/{grant_id}/revoke", dependencies=[Depends(mutation)])
    def revoke(grant_id: str, body: StrictBody, context=Depends(identity)):
        return bank.revoke(context, grant_id)

    @routes.post("/transfers/prepare", dependencies=[Depends(mutation)])
    def prepare(body: TransferBody, context=Depends(identity)):
        return bank.prepare(context, body.model_dump())

    @routes.post("/subscriptions/cancel/prepare", dependencies=[Depends(mutation)])
    def cancel(body: CancelBody, context=Depends(identity)):
        return bank.prepare(context, body.model_dump(), "cancel_subscription")

    @routes.get("/operations/{operation_id}")
    def operation(operation_id: str, context=Depends(identity)):
        return bank.operation(context, operation_id)

    @routes.get("/operations")
    def operations(
        limit: int = Query(50, ge=1, le=100),
        task_id: str | None = None,
        context=Depends(identity),
    ):
        return {"operations": bank.operations(context, limit, task_id)}

    @routes.post("/operations/{operation_id}/challenge", dependencies=[Depends(mutation)])
    def challenge(operation_id: str, body: StrictBody, context=Depends(identity)):
        return bank.challenge(context, operation_id)

    @routes.post("/operations/{operation_id}/decision", dependencies=[Depends(mutation)])
    def decision(operation_id: str, body: DecisionBody, context=Depends(identity)):
        return bank.decide(
            context, operation_id, body.decision, body.challenge, body.parameters_digest
        )

    @routes.post("/operations/{operation_id}/execute", dependencies=[Depends(mutation)])
    def execute(operation_id: str, body: StrictBody, context=Depends(identity)):
        return bank.execute(context, operation_id)

    @routes.post("/operations/{operation_id}/reconcile", dependencies=[Depends(mutation)])
    def reconcile(operation_id: str, body: StrictBody, context=Depends(identity)):
        return bank.reconcile(context, operation_id)

    @routes.get("/events")
    def events(
        after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), context=Depends(identity)
    ):
        rows = bank.events(context, after, limit)
        return {"events": rows, "next_after": rows[-1]["seq"] if rows else after}

    @routes.get("/reports")
    def report(start: date, end: date, context=Depends(identity)):
        return reports.bills(context, start, end)

    @routes.get("/subscriptions")
    def subscriptions(context=Depends(identity)):
        return reports.subscriptions(context)

    @routes.get("/reports/entries")
    def report_entries(
        start: date,
        end: date,
        category: str | None = Query(None, max_length=128),
        entry_id: str | None = Query(None, max_length=64),
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=50),
        context=Depends(identity),
    ):
        return reports.entries(context, start, end, category, entry_id, offset, limit)

    @routes.post(
        "/subscriptions/candidates/{candidate_id}/confirm", dependencies=[Depends(mutation)]
    )
    def confirm_subscription(
        candidate_id: str, body: SubscriptionRegistrationBody, context=Depends(identity)
    ):
        return reports.confirm_candidate(context, candidate_id, body.evidence_digest)

    return routes
