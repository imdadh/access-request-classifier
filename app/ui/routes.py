import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.models import AccessRequest, RequestStatus
from app.db.session import get_db

router = APIRouter(prefix="", tags=["ui"])

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse, name="ui_submit")
async def submit_form(request: Request, db: Session = Depends(get_db)):
    """Render the end-user submission form and show user's recent requests."""
    # Show recent requests for display (optional, template may handle)
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

    # Parse anomaly_factors from JSON string to list
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
