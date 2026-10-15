import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.auth import require_api_key
from src.data_adapter import search_helpdesk
from src.db.models import ExecutionStep, Task, TaskRun
from src.db.session import Base, SessionLocal, engine
from src.llm.analysis import LLMAnalysisError, analyze_findings

# Actions that must not be executed without explicit human authorization.
SENSITIVE_ACTIONS = {
    "reset_account",
    "restart_device",
    "change_config",
    "network_change",
}

# Import chat modules
from src.conversations.models import (
    Conversation, 
    Message, 
    CreateConversationRequest, 
    SendMessageRequest,
    MessageRole
)
from src.conversations.store import (
    create_conversation,
    get_conversation,
    update_conversation,
    delete_conversation,
    add_message,
    get_messages,
    list_conversations,
    set_agent_status,
    get_agent_status,
)
from src.workflows.chat import create_chat_workflow
from src.llm.litellm_client import (
    FallbackLLMClient,
    LiteLLMClient,
    OpenAIChatClient,
)
from src.config.settings import Settings
from src.llm.prompts import HELPDESK_SYSTEM_PROMPT, NETWORK_SYSTEM_PROMPT, CAMPUS_SYSTEM_PROMPT
from src.data_adapter import search_helpdesk

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Convenience untuk pengembangan lokal.
    # Untuk deployment, gunakan migrasi Alembic.
    try:
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError as exc:
        # Conversation endpoints use the local store and can still serve development
        # requests when the optional task database is not running.
        print(f"Database startup check failed; database-backed routes may be unavailable: {exc}")
    yield


app = FastAPI(
    title="DinusNexus API",
    version="0.1.0",
    lifespan=lifespan,
)

from src.account_api import router as account_router

app.include_router(account_router)


def cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# Allow the frontend (served from another origin) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize settings and LLM client
settings = Settings()
def _build_llm_client() -> FallbackLLMClient:
    primary = None
    fallback = None
    primary_is_openai = settings.llm_provider.strip().lower() == "openai"
    if primary_is_openai:
        if settings.openai.api_key:
            primary = OpenAIChatClient(settings.openai)
        if settings.llm_fallback_enabled and settings.llm.base_url and settings.llm.api_key:
            fallback = LiteLLMClient(settings.llm)
    else:
        if settings.llm.base_url and settings.llm.api_key:
            primary = LiteLLMClient(settings.llm)
        if settings.llm_fallback_enabled and settings.openai.api_key:
            fallback = OpenAIChatClient(settings.openai)
    return FallbackLLMClient(primary, fallback)


llm_client = _build_llm_client()

# Chat workflow
chat_workflow = create_chat_workflow()

class CreateTaskInput(BaseModel):
    worker: Literal["it_helpdesk"] = "it_helpdesk"
    description: str = Field(min_length=5, max_length=2000)
    location: str | None = None
    device_type: str | None = None
    requested_action: str | None = Field(default=None, max_length=100)


class ApprovalInput(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


class WorkflowState(TypedDict):
    task_id: str
    description: str
    location: str | None
    device_type: str | None
    requested_action: str | None
    requires_approval: bool
    status: str
    steps: list[dict]
    findings: dict
    analysis: dict
    result: dict


class StepFailedError(RuntimeError):
    """Raised by a workflow node that fails after recording a failed step."""

    def __init__(self, steps: list[dict], code: str, message: str):
        super().__init__(message)
        self.steps = steps
        self.code = code
        self.message = message


def llm_enabled() -> bool:
    """Whether the optional LLM analysis step should run."""
    return os.getenv("LLM_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def serialize_task(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "run_id": task.run_id,
        "worker": task.worker,
        "description": task.description,
        "location": task.location,
        "device_type": task.device_type,
        "requested_action": task.requested_action,
        "status": task.status,
        "created_at": task.created_at.isoformat(),
        "steps": task.steps,
        "result": task.result,
        "error": task.error,
        "approval": task.approval,
        "llm_model": task.llm_model,
        "input_tokens": task.input_tokens,
        "output_tokens": task.output_tokens,
    }


def serialize_run(run: TaskRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "task_id": run.task_id,
        "worker": run.worker,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "steps": [
            {
                "step_id": step.step_key,
                "order": step.order_index,
                "name": step.name,
                "status": step.status,
                "source_ids": step.source_ids,
                "detail": step.detail,
                "error": step.error,
                "model": step.model,
                "usage": step.usage,
            }
            for step in run.steps
        ],
    }


def persist_run(db, task: Task, steps: list[dict]) -> None:
    """Write the normalized run and its ordered steps. Idempotent per task."""
    now = datetime.now(timezone.utc)
    run = db.get(TaskRun, task.run_id)
    if run is None:
        run = TaskRun(
            run_id=task.run_id,
            task_id=task.task_id,
            worker=task.worker,
            status=task.status,
            created_at=task.created_at,
            finished_at=now,
        )
        db.add(run)
    else:
        run.worker = task.worker
        run.status = task.status
        run.finished_at = now

    # Replace the step rows so repeated finalization stays in sync.
    db.query(ExecutionStep).filter(
        ExecutionStep.run_id == task.run_id
    ).delete(synchronize_session=False)

    for index, step in enumerate(steps, start=1):
        db.add(
            ExecutionStep(
                run_id=task.run_id,
                order_index=index,
                step_key=step.get("step_id"),
                name=step.get("name", ""),
                status=step.get("status", ""),
                source_ids=step.get("source_ids"),
                detail=step.get("detail"),
                error=step.get("error"),
                model=step.get("model"),
                usage=step.get("usage"),
            )
        )


def extract_usage(result: dict | None) -> tuple[str | None, int | None, int | None]:
    """Pull ``(model, input_tokens, output_tokens)`` from a workflow result."""
    analysis = (result or {}).get("analysis") or {}
    model = analysis.get("model")
    usage = analysis.get("usage") or {}
    if not isinstance(usage, dict):
        return model, None, None
    return (
        model,
        usage.get("input_tokens"),
        usage.get("output_tokens"),
    )


def inspect_report(state: WorkflowState) -> dict:
    findings = search_helpdesk(
        state["description"],
        zone_id=state.get("location"),
        device_type=state.get("device_type"),
    )

    source_ids = [
        record["id"]
        for records in findings["matches"].values()
        for record in records
        if "id" in record
    ]

    requested_action = (state.get("requested_action") or "").strip().lower() or None
    requires_approval = requested_action in SENSITIVE_ACTIONS

    return {
        "status": "running",
        "findings": findings,
        "requested_action": requested_action,
        "requires_approval": requires_approval,
        "steps": [
            {
                "step_id": "inspect_report",
                "name": "Search synthetic helpdesk data",
                "status": "completed",
                "source_ids": source_ids,
            }
        ],
    }


def analyze_evidence(state: WorkflowState) -> dict:
    """Optional LLM step. Disabled by default (LLM_ENABLED=false)."""
    steps = state["steps"]

    if not llm_enabled():
        return {
            "status": "running",
            "analysis": {},
            "steps": steps + [
                {
                    "step_id": "analyze_evidence",
                    "name": "Analyze evidence with LLM",
                    "status": "skipped",
                    "detail": "LLM analysis disabled (LLM_ENABLED is not set).",
                }
            ],
        }

    try:
        analysis = analyze_findings(
            state["description"],
            state["findings"],
            location=state.get("location"),
            device_type=state.get("device_type"),
        )
    except LLMAnalysisError as exc:
        # Record the failed step and let create_task persist a failed task.
        # Never let a failed LLM step be reported as completed.
        failed_step = {
            "step_id": "analyze_evidence",
            "name": "Analyze evidence with LLM",
            "status": "failed",
            "error": {
                "code": "LLM_ANALYSIS_FAILED",
                "message": "The language model analysis failed.",
            },
        }
        raise StepFailedError(
            steps=steps + [failed_step],
            code="LLM_ANALYSIS_FAILED",
            message="The language model analysis failed.",
        ) from exc

    return {
        "status": "running",
        "analysis": analysis,
        "steps": steps + [
            {
                "step_id": "analyze_evidence",
                "name": "Analyze evidence with LLM",
                "status": "completed",
                "model": analysis.get("model"),
                "usage": analysis.get("usage"),
            }
        ],
    }


def prepare_result(state: WorkflowState) -> dict:
    findings = state["findings"]
    analysis = state.get("analysis") or {}

    facts = [
        {"dataset": dataset_name, "record": record}
        for dataset_name, records in findings["matches"].items()
        for record in records
    ]

    evidence = [
        {"source_id": record["id"], "dataset": dataset_name}
        for dataset_name, records in findings["matches"].items()
        for record in records
        if "id" in record
    ]

    interpretation = [
        f"Found {len(facts)} matching records in synthetic datasets."
    ]
    uncertainty = [
        "These records are synthetic and do not represent verified live campus conditions."
    ]
    recommendations = [
        "Verify the relevant device and incident details before taking action."
    ]

    if analysis:
        if analysis.get("summary"):
            interpretation.append(analysis["summary"])
        uncertainty.extend(analysis.get("uncertainty", []))
        recommendations.extend(analysis.get("recommendations", []))

    return {
        "status": "completed",
        "steps": state["steps"] + [
            {
                "step_id": "prepare_result",
                "name": "Prepare result from synthetic data",
                "status": "completed",
                "source_ids": [
                    item["source_id"] for item in evidence
                ],
            }
        ],
        "result": {
            "facts": facts,
            "evidence": evidence,
            "analysis": analysis or None,
            "interpretation": interpretation,
            "uncertainty": uncertainty,
            "recommendations": recommendations,
            "data_label": "SYNTHETIC",
        },
    }


def request_approval(state: WorkflowState) -> dict:
    """Stop before a sensitive action and wait for a human decision."""
    action = state.get("requested_action")
    approval = {
        "required": True,
        "status": "pending",
        "action": action,
        "note": "No sensitive action is executed automatically.",
    }

    return {
        "status": "waiting_for_approval",
        "steps": state["steps"] + [
            {
                "step_id": "request_approval",
                "name": "Await human approval",
                "status": "waiting_for_approval",
                "detail": f"Action '{action}' requires human approval.",
            }
        ],
        "result": {**state["result"], "approval": approval},
    }


workflow = StateGraph(WorkflowState)
workflow.add_node("inspect_report", inspect_report)
workflow.add_node("analyze_evidence", analyze_evidence)
workflow.add_node("prepare_result", prepare_result)
workflow.add_node("request_approval", request_approval)
workflow.add_edge(START, "inspect_report")
workflow.add_edge("inspect_report", "analyze_evidence")
workflow.add_edge("analyze_evidence", "prepare_result")


def route_after_prepare(state: WorkflowState) -> str:
    if state.get("requires_approval"):
        return "request_approval"
    return END


workflow.add_conditional_edges(
    "prepare_result",
    route_after_prepare,
    {"request_approval": "request_approval", END: END},
)
workflow.add_edge("request_approval", END)

helpdesk_graph = workflow.compile()


def _persist_failed_task(
    task_id: str,
    steps: list[dict] | None,
    code: str,
    message: str,
) -> None:
    """Best-effort persistence of a failed task without masking the original error."""
    try:
        with SessionLocal() as db:
            saved_task = db.get(Task, task_id)
            if saved_task is None:
                return
            saved_task.status = "failed"
            if steps is not None:
                saved_task.steps = steps
            saved_task.error = {"code": code, "message": message}
            persist_run(db, saved_task, saved_task.steps or [])
            db.commit()
    except SQLAlchemyError:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "dinusnexus-api"}


@app.post("/api/tasks", status_code=201)
def create_task(
    payload: CreateTaskInput,
    _: None = Depends(require_api_key),
):
    task = Task(
        task_id=str(uuid4()),
        run_id=str(uuid4()),
        worker=payload.worker,
        description=payload.description,
        location=payload.location,
        device_type=payload.device_type,
        requested_action=payload.requested_action,
        status="queued",
        created_at=datetime.now(timezone.utc),
        steps=[],
        result=None,
        error=None,
    )

    # Simpan task terlebih dahulu agar task tercatat di database.
    try:
        with SessionLocal() as db:
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.task_id
            run_id = task.run_id
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable; task could not be saved.",
        ) from exc

    try:
        output = helpdesk_graph.invoke({
            "task_id": task_id,
            "description": payload.description,
            "location": payload.location,
            "device_type": payload.device_type,
            "requested_action": payload.requested_action,
            "requires_approval": False,
            "status": "queued",
            "steps": [],
            "findings": {},
            "analysis": {},
            "result": {},
        })

        with SessionLocal() as db:
            saved_task = db.get(Task, task_id)
            if saved_task is None:
                raise RuntimeError("Task disappeared from database.")

            model, input_tokens, output_tokens = extract_usage(output.get("result"))
            saved_task.status = output["status"]
            saved_task.steps = output["steps"]
            saved_task.result = output["result"]
            saved_task.requested_action = output.get("requested_action")
            if output["status"] == "waiting_for_approval":
                saved_task.approval = (output.get("result") or {}).get("approval")
            saved_task.llm_model = model
            saved_task.input_tokens = input_tokens
            saved_task.output_tokens = output_tokens
            persist_run(db, saved_task, output["steps"])
            db.commit()
            db.refresh(saved_task)
            return serialize_task(saved_task)

    except StepFailedError as exc:
        _persist_failed_task(task_id, exc.steps, exc.code, exc.message)
        raise HTTPException(
            status_code=500,
            detail={
                "task_id": task_id,
                "run_id": run_id,
                "error": {"code": exc.code, "message": exc.message},
            },
        ) from exc
    except Exception as exc:
        _persist_failed_task(
            task_id,
            None,
            "WORKFLOW_FAILED",
            "The workflow could not complete.",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "task_id": task_id,
                "run_id": run_id,
                "error": {
                    "code": "WORKFLOW_FAILED",
                    "message": "The workflow could not complete.",
                },
            },
        ) from exc


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    _: None = Depends(require_api_key),
):
    try:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise HTTPException(
                    status_code=404,
                    detail="Task not found",
                )
            return serialize_task(task)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable.",
        ) from exc


@app.post("/api/tasks/{task_id}/approval")
def decide_task_approval(
    task_id: str,
    payload: ApprovalInput,
    _: None = Depends(require_api_key),
):
    """Record a human approve/reject decision for a task awaiting approval."""
    try:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            if task.status != "waiting_for_approval":
                raise HTTPException(
                    status_code=409,
                    detail="Task is not waiting for approval.",
                )

            approved = payload.decision == "approve"
            approval = {
                **(task.approval or {}),
                "status": "approved" if approved else "rejected",
                "decision": payload.decision,
                "note": payload.note,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
            task.approval = approval
            task.status = "completed" if approved else "cancelled"

            steps = list(task.steps or [])
            steps.append(
                {
                    "step_id": "approval",
                    "name": "Human approval decision",
                    "status": task.status,
                    "detail": f"Decision: {payload.decision}",
                }
            )
            task.steps = steps

            result = dict(task.result or {})
            result["approval"] = approval
            task.result = result

            persist_run(db, task, steps)
            db.commit()
            db.refresh(task)
            return serialize_task(task)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable.",
        ) from exc


@app.get("/api/tasks/{task_id}/runs")
def get_task_runs(
    task_id: str,
    _: None = Depends(require_api_key),
):
    """Read the normalized run and execution steps for a task."""
    try:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            runs = db.scalars(
                select(TaskRun)
                .where(TaskRun.task_id == task_id)
                .order_by(TaskRun.created_at.desc())
            ).all()
            return {"items": [serialize_run(run) for run in runs]}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable.",
        ) from exc


@app.get("/api/history")
def get_history(
    _: None = Depends(require_api_key),
):
    try:
        with SessionLocal() as db:
            statement = select(Task).order_by(Task.created_at.desc())
            tasks = db.scalars(statement).all()
            return {
                "items": [serialize_task(task) for task in tasks]
            }
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable.",
        ) from exc


@app.get("/api/metrics/tokens")
def get_token_metrics(
    _: None = Depends(require_api_key),
):
    """Aggregate LLM token usage across all persisted tasks."""
    try:
        with SessionLocal() as db:
            total_tasks = db.scalar(select(func.count()).select_from(Task)) or 0

            input_total, output_total, tasks_with_usage = db.execute(
                select(
                    func.coalesce(func.sum(Task.input_tokens), 0),
                    func.coalesce(func.sum(Task.output_tokens), 0),
                    func.count(Task.input_tokens),
                )
            ).one()

            by_model = [
                {
                    "model": model,
                    "tasks": tasks,
                    "input_tokens": input_sum or 0,
                    "output_tokens": output_sum or 0,
                }
                for model, tasks, input_sum, output_sum in db.execute(
                    select(
                        Task.llm_model,
                        func.count(),
                        func.coalesce(func.sum(Task.input_tokens), 0),
                        func.coalesce(func.sum(Task.output_tokens), 0),
                    )
                    .where(Task.llm_model.isnot(None))
                    .group_by(Task.llm_model)
                ).all()
            ]

            items = [
                {
                    "task_id": task.task_id,
                    "model": task.llm_model,
                    "input_tokens": task.input_tokens,
                    "output_tokens": task.output_tokens,
                    "created_at": task.created_at.isoformat(),
                }
                for task in db.scalars(
                    select(Task)
                    .where(Task.input_tokens.isnot(None))
                    .order_by(Task.created_at.desc())
                ).all()
            ]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable.",
        ) from exc

    return {
        "totals": {
            "tasks": int(total_tasks),
            "tasks_with_usage": int(tasks_with_usage),
            "input_tokens": int(input_total),
            "output_tokens": int(output_total),
            "unavailable": int(total_tasks) - int(tasks_with_usage),
        },
        "by_model": by_model,
        "items": items,
    }


# Chat endpoints
@app.post("/api/conversations", status_code=201, dependencies=[Depends(require_api_key)])
def create_conversation_endpoint(payload: CreateConversationRequest):
    """Create a new conversation"""
    conversation_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    conversation = Conversation(
        conversation_id=conversation_id,
        worker=payload.worker,
        title=payload.title or f"Conversation {conversation_id[:8]}",
        created_at=now,
        updated_at=now,
        messages=[]
    )
    
    create_conversation(conversation)
    return conversation


@app.get("/api/conversations", dependencies=[Depends(require_api_key)])
def list_conversations_endpoint():
    """List all conversations"""
    return list_conversations()


@app.get("/api/conversations/{conversation_id}", dependencies=[Depends(require_api_key)])
def get_conversation_detail(conversation_id: str):
    """Get a specific conversation with all messages"""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Add messages to conversation
    messages = get_messages(conversation_id)
    conversation.messages = messages
    return conversation


@app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(require_api_key)])
def delete_conversation_endpoint(conversation_id: str):
    """Delete a conversation"""
    deleted = delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": "Conversation deleted successfully"}


@app.get(
    "/api/conversations/{conversation_id}/agent-status",
    dependencies=[Depends(require_api_key)],
)
def get_agent_status_endpoint(conversation_id: str):
    """Return the latest backend phase for the active agent request."""
    if get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return get_agent_status(conversation_id) or {
        "phase": "idle",
        "status": "idle",
        "detail": "Menunggu pesan.",
    }


@app.post(
    "/api/conversations/{conversation_id}/messages",
    status_code=201,
    dependencies=[Depends(require_api_key)],
)
async def send_message(conversation_id: str, payload: SendMessageRequest):
    """Send a message in a conversation"""
    # Get conversation
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Determine worker from conversation
    worker = conversation.worker or "it_helpdesk"
    set_agent_status(
        conversation_id,
        "received",
        "running",
        "Pesan diterima oleh agent.",
    )
    
    # Select system prompt based on worker
    system_prompts = {
        "it_helpdesk": HELPDESK_SYSTEM_PROMPT,
        "network_operations": NETWORK_SYSTEM_PROMPT,
        "campus_operations": CAMPUS_SYSTEM_PROMPT,
    }
    system_prompt = system_prompts.get(worker, HELPDESK_SYSTEM_PROMPT)
    
    # Create user message
    user_message = Message(
        message_id=str(uuid4()),
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=payload.content,
        created_at=datetime.now(timezone.utc),
        metadata={
            "attachments": payload.attachments,
            "context": payload.context
        }
    )
    
    # Add user message
    add_message(user_message)
    
    from src.conversations.context import (
        build_chat_evidence, evidence_prompt, provider_history, validate_source_mentions,
    )

    try:
        set_agent_status(conversation_id, "retrieving_evidence", "running", "Mencari evidence dari adapter data sintetis.")
        all_messages = get_messages(conversation_id)
        bundle = build_chat_evidence(worker, all_messages)
        set_agent_status(
            conversation_id,
            "analyzing",
            "running",
            "Agent menganalisis evidence dengan policy worker.",
        )
        response = await llm_client.chat_completion([
            {"role": "system", "content": system_prompt + evidence_prompt(bundle)},
            *provider_history(all_messages)
        ])
        if not response.content.strip() or not validate_source_mentions(response.content, bundle["evidence"]):
            raise ValueError("Invalid agent response")
        
        # Create assistant message
        assistant_message = Message(
            message_id=str(uuid4()),
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=response.content,
            created_at=datetime.now(timezone.utc),
            metadata={
                "tokens_used": response.usage,
                "model": response.model,
                "worker": worker,
                "data_label": bundle["data_label"],
                "sources": list(dict.fromkeys(e["source_id"] for e in bundle["evidence"])),
                "evidence": bundle["evidence"],
                "evidence_counts": bundle["counts"],
                "derived": bundle["derived"],
                "limitations": bundle["limitations"],
            }
        )
        
        # Add assistant message
        set_agent_status(
            conversation_id,
            "saving_response",
            "running",
            "Menyimpan jawaban, metadata, dan sumber.",
        )
        add_message(assistant_message)
        set_agent_status(
            conversation_id,
            "completed",
            "completed",
            "Analisis selesai dan respons tersimpan.",
        )
        
        # Return the response
        return assistant_message
        
    except Exception:
        logger.exception("Conversation LLM request failed for worker=%s", worker)
        set_agent_status(
            conversation_id,
            "failed",
            "failed",
            "Provider agent gagal memproses permintaan.",
        )
        safe_error = (
            "Maaf, agent belum dapat memproses permintaan. "
            "Periksa koneksi provider atau coba lagi."
        )
        error_message = Message(
            message_id=str(uuid4()),
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=safe_error,
            created_at=datetime.now(timezone.utc),
            metadata={"error": "llm_unavailable", "worker": worker}
        )
        add_message(error_message)
        raise HTTPException(status_code=502, detail=safe_error)


from src.event_api import event_router


def create_event_helpdesk(description: str, zone_id: str):
    return create_task(CreateTaskInput(description=description, location=zone_id, device_type="access_point"), None)


app.include_router(event_router(serialize_task, persist_run, _persist_failed_task, create_event_helpdesk))


from src.vision_api import router as vision_router

app.include_router(vision_router)

from src.twin_api import router as twin_router

app.include_router(twin_router)
