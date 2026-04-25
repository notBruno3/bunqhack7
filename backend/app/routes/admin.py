from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, Ticket, Transaction
from ..schemas import AuditLogOut, TicketDecisionReq, TicketOut, Verdict

router = APIRouter()


def _ticket_to_out(db: Session, ticket: Ticket) -> TicketOut:
    tx = db.get(Transaction, ticket.transaction_id)
    audit = db.get(AuditLog, ticket.audit_log_id)
    if not tx or not audit:
        raise HTTPException(status_code=500, detail="ticket_missing_relations")
    return TicketOut(
        id=ticket.id,
        transaction_id=ticket.transaction_id,
        verification_id=ticket.verification_id,
        status=ticket.status,  # type: ignore[arg-type]
        tier=tx.tier,  # type: ignore[arg-type]
        amount_eur=tx.amount_eur,
        merchant=tx.merchant,
        user_id=tx.user_id,
        created_at=ticket.created_at,
        audit_log=_audit_to_out(audit),
    )


def _audit_to_out(audit: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=audit.id,
        verification_id=audit.verification_id,
        transaction_id=audit.transaction_id,
        tier=audit.tier,  # type: ignore[arg-type]
        hume_scores=audit.hume_scores,  # type: ignore[arg-type]
        gemini_summary=audit.gemini_summary,  # type: ignore[arg-type]
        merchant_reputation=audit.merchant_reputation,  # type: ignore[arg-type]
        verdict=Verdict.model_validate(audit.verdict),
        started_at=audit.started_at,
        decided_at=audit.decided_at,
        duration_ms=audit.duration_ms,
    )


@router.get("/tickets", response_model=list[TicketOut])
def list_tickets(
    status: str | None = None, db: Session = Depends(get_db)
) -> list[TicketOut]:
    q = select(Ticket).order_by(Ticket.created_at.desc())
    if status:
        q = q.where(Ticket.status == status.upper())
    tickets = db.scalars(q).all()
    return [_ticket_to_out(db, t) for t in tickets]


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: str, db: Session = Depends(get_db)) -> TicketOut:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return _ticket_to_out(db, ticket)


@router.post("/tickets/{ticket_id}/decision", response_model=TicketOut)
def decide_ticket(
    ticket_id: str, req: TicketDecisionReq, db: Session = Depends(get_db)
) -> TicketOut:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    if ticket.status != "OPEN":
        raise HTTPException(status_code=400, detail="ticket_already_decided")

    tx = db.get(Transaction, ticket.transaction_id)
    if not tx:
        raise HTTPException(status_code=500, detail="transaction_missing")

    if req.action == "approve":
        ticket.status = "APPROVED"
        tx.status = "APPROVED"
    else:
        ticket.status = "REJECTED"
        tx.status = "REJECTED"
    ticket.note = req.note or ""
    ticket.decided_at = datetime.utcnow()
    db.commit()
    return _ticket_to_out(db, ticket)


@router.get("/audit_logs", response_model=list[AuditLogOut])
def list_audit_logs(db: Session = Depends(get_db)) -> list[AuditLogOut]:
    logs = db.scalars(select(AuditLog).order_by(AuditLog.decided_at.desc())).all()
    return [_audit_to_out(a) for a in logs]
