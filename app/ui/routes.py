import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.models import AccessRequest, RequestStatus, RequestType
from app.db.session import get_db
from app.repositories.audit import update_request_classification

router = APIRouter(prefix="", tags=["ui"])

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse, name="ui_submit")
async def submit_form(request: Request, db: Session = Depends(get_db)):
    """Render the end-user submission form and show user's recent requests."""
    recent_requests = (
        db.query(AccessRequest)
        .order_by(AccessRequest.created_at.desc())
        .limit(10)
        .all()
    )
    return templates.TemplateResponse(
        "submit.html",
        {"request": request, "recent_requests": recent_requests},
    )


@router.get("/queue", response_class=HTMLResponse, name="ui_queue")
async def review_queue(request: Request, db: Session = Depends(get_db)):
    """Render the reviewer queue listing all pending requests."""
    pending_requests = (
        db.query(AccessRequest)
        .filter(AccessRequest.status == RequestStatus.PENDING_REVIEW)
        .order_by(AccessRequest.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "review_queue.html",
        {"request": request, "pending_requests": pending_requests},
    )


@router.get("/detail/{request_id}", response_class=HTMLResponse, name="ui_detail")
async def review_detail(
    request: Request, request_id: int, db: Session = Depends(get_db)
):
    """Render the reviewer detail screen for a specific request."""
    req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    anomaly_factors: Optional[list[str]] = None
    if req.anomaly_factors:
        try:
            anomaly_factors = json.loads(req.anomaly_factors)
        except (json.JSONDecodeError, TypeError):
            anomaly_factors = [str(req.anomaly_factors)]

    return templates.TemplateResponse(
        "review_detail.html",
        {
            "request": request,
            "access_request": req,
            "anomaly_factors": anomaly_factors,
        },
    )


@router.post("/detail/{request_id}/approve", response_class=HTMLResponse)
async def approve_request(
    request: Request,
    request_id: int,
    db: Session = Depends(get_db),
):
    """Approve a pending access request."""
    req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Request is not pending review")

    update_request_classification(
        db=db,
        request_id=request_id,
        classification=req.classification or RequestType.DATA_ACCESS,
        classification_confidence=req.classification_confidence,
        anomaly_score=req.anomaly_score,
        recommended_approver=req.recommended_approver or "",
        status=RequestStatus.APPROVED,
        actor="reviewer",
    )
    return RedirectResponse(url=router.url_path_for("ui_queue"), status_code=303)


@router.post("/detail/{request_id}/reject", response_class=HTMLResponse)
async def reject_request(
    request: Request,
    request_id: int,
    db: Session = Depends(get_db),
):
    """Reject a pending access request."""
    req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Request is not pending review")

    update_request_classification(
        db=db,
        request_id=request_id,
        classification=req.classification or RequestType.DATA_ACCESS,
        classification_confidence=req.classification_confidence,
        anomaly_score=req.anomaly_score,
        recommended_approver=req.recommended_approver or "",
        status=RequestStatus.REJECTED,
        actor="reviewer",
    )
    return RedirectResponse(url=router.url_path_for("ui_queue"), status_code=303)


@router.post("/detail/{request_id}/override", response_class=HTMLResponse)
async def override_request(
    request: Request,
    request_id: int,
    classification: str = Form(...),
    classification_confidence: float = Form(..., ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """Override the classification of a pending request and approve it."""
    req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Request is not pending review")

    # Validate classification enum
    try:
        new_classification = RequestType(classification)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid classification '{classification}'. Must be one of {[e.value for e in RequestType]}",
        )

    update_request_classification(
        db=db,
        request_id=request_id,
        classification=new_classification,
        classification_confidence=classification_confidence,
        anomaly_score=req.anomaly_score,
        recommended_approver=req.recommended_approver or "",
        status=RequestStatus.APPROVED,
        actor="reviewer",
    )
    return RedirectResponse(url=router.url_path_for("ui_queue"), status_code=303)
