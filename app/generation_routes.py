"""Creator-only job API. JSON writes reject cross-origin requests."""
import json
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, generation, ingest
from app.db import get_session
from app.generation import ACTIVE, PLAYABLE, PUBLISHED, READY
from app.identity import current_identity
from app.models import Generation, GenerationEvent, utcnow

router = APIRouter(prefix="/api/generations")

MAX_EVENTS_PER_JOB = 200


def creator(request: Request, identity=Depends(current_identity)):
    user, _ = identity
    if user is None:
        raise HTTPException(401, "先认领一个身份，再开始创作吧")
    if request.method != "GET":
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Invalid origin")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "JSON required")
    return user


def owned(session, job_id, user):
    job = session.get(Generation, job_id)
    if job is None or job.user_id != user.id or job.claim_hash != generation.fingerprint(user.claim_token or ""):
        raise HTTPException(404, "找不到这个创作")
    return job


def job_payload(job):
    return dict(id=job.id, prompt=job.prompt, status=job.status, active=job.status in ACTIVE,
                details=json.loads(job.details), error=job.error, timings=json.loads(job.timings),
                elapsed_ms=generation.elapsed(job), work_id=job.work_id,
                preview_url=f"/api/generations/{job.id}/preview",
                playtested=job.playtest_at is not None)


class Start(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    request_id: uuid.UUID


class Details(BaseModel):
    title: str = Field(default="", max_length=120)
    category: str = Field(default="", max_length=24)
    emoji: str = Field(default="🎮", max_length=8)
    art: Literal["art-one", "art-two", "art-three", "art-four"] = "art-one"
    description: str = Field(default="", max_length=200)


class Signal(BaseModel):
    kind: Literal["playtest_opened", "playtest_loaded", "playtest_error", "playtest_timeout", "playtest_closed"]
    elapsed_ms: int | None = Field(default=None, ge=0, le=86400000)


@router.get("/current")
def current_generation(user=Depends(creator), session: Session = Depends(get_session)):
    job = session.scalar(select(Generation).where(Generation.user_id == user.id,
        Generation.claim_hash == generation.fingerprint(user.claim_token or "")).order_by(Generation.created_at.desc()))
    return {"configured": bool(config.EVOMAP_KEYS), "job": job_payload(job) if job else None}


@router.post("", status_code=202)
def start_generation(body: Start, user=Depends(creator), session: Session = Depends(get_session)):
    if not body.prompt.strip():
        raise HTTPException(422, "先写下一句想法吧")
    with generation.LOCK:
        existing = session.get(Generation, str(body.request_id))
        if existing:
            return job_payload(owned(session, existing.id, user))
        if not config.EVOMAP_KEYS:
            raise HTTPException(503, "生成服务尚未配置，请联系管理员添加 API key")
        if session.scalar(select(Generation.id).where(Generation.user_id == user.id, Generation.status.in_(ACTIVE))):
            raise HTTPException(409, "这个身份已有一个游戏正在生成")
        job = Generation(id=str(body.request_id), user_id=user.id,
            claim_hash=generation.fingerprint(user.claim_token or ""),
            prompt=body.prompt.strip(), model=config.EVOMAP_MODEL)
        session.add(job)
        session.flush()
        generation.emit(session, job, "submitted", 0)
        session.commit()
        return job_payload(job)


@router.get("/{job_id}")
def get_generation(job_id: str, user=Depends(creator), session: Session = Depends(get_session)):
    return job_payload(owned(session, job_id, user))


@router.put("/{job_id}/details")
def save_details(job_id: str, body: Details, user=Depends(creator), session: Session = Depends(get_session)):
    with generation.LOCK:
        job = owned(session, job_id, user)
        if job.work_id:
            raise HTTPException(409, "已发布的作品不能在这里修改")
        job.details = body.model_dump_json()
        try:
            ingest.validate_details(**body.model_dump())
        except ingest.DetailsError:
            # This is autosave: keep the half-filled draft, but only complete
            # details count as the creator having finished this step.
            session.commit()
            return job_payload(job)
        if job.details_at is None:
            job.details_at = utcnow()
            generation.update_timings(job, details_ms=generation.elapsed(job))
            if job.finished_at and job.status == READY:
                generation.update_timings(job, idle_wait_ms=generation.since_ms(job.details_at, job.finished_at))
            generation.emit(session, job, "details_completed", generation.elapsed(job))
        session.commit()
        return job_payload(job)


@router.get("/{job_id}/preview", response_class=HTMLResponse)
def preview(job_id: str, user=Depends(creator), session: Session = Depends(get_session)):
    job = owned(session, job_id, user)
    if job.status not in PLAYABLE or not job.html:
        raise HTTPException(409, "游戏还没准备好")
    return HTMLResponse(job.html, headers={"Cache-Control": "no-store",
        "Content-Security-Policy": generation.CSP + "; sandbox allow-scripts; frame-ancestors 'self'",
        "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})


@router.post("/{job_id}/events", status_code=204)
def record_event(job_id: str, body: Signal, user=Depends(creator), session: Session = Depends(get_session)):
    with generation.LOCK:
        job = owned(session, job_id, user)
        if job.status not in PLAYABLE:
            raise HTTPException(409, "游戏还没准备好")
        count = session.scalar(select(func.count()).select_from(GenerationEvent).where(GenerationEvent.generation_id == job.id))
        if count >= MAX_EVENTS_PER_JOB:
            raise HTTPException(429, "Too many events")
        if body.kind == "playtest_loaded" and job.playtest_at is None:
            job.playtest_at = utcnow()
        generation.emit(session, job, body.kind, body.elapsed_ms)
        if body.kind == "playtest_opened" and "to_playtest_ms" not in json.loads(job.timings):
            generation.update_timings(job, to_playtest_ms=generation.elapsed(job))
        session.commit()


@router.post("/{job_id}/publish")
def publish(job_id: str, body: Details, user=Depends(creator), session: Session = Depends(get_session)):
    with generation.LOCK:
        job = owned(session, job_id, user)
        if job.work_id:
            return {"work_id": job.work_id}
        if job.status != READY or not job.html or not job.playtest_at:
            raise HTTPException(409, "先试玩一下，再发布吧")
        try:
            info = ingest.validate_details(**body.model_dump())
        except ingest.DetailsError as error:
            raise HTTPException(422, str(error)) from error
        work = ingest.publish(session, owner=user, details=info,
            entries=[("index.html", job.html.encode())], actor=f"user:{user.slug}", commit=False)
        job.work_id, job.status, job.details = work.id, PUBLISHED, json.dumps(asdict(info))
        generation.emit(session, job, "published", generation.elapsed(job))
        session.commit()
    ingest.announce(work, user)
    return {"work_id": work.id}
