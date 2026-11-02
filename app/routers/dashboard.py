"""Dashboard ringkas berbasis periode."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import require_user
from app.services import dashboard
from app.services.periods import build_period_context, resolve_period
from app.templating import templates

router = APIRouter()


@router.get("/")
def dashboard_page(
    request: Request,
    period_type: str = Query(""),
    period: str = Query(""),
    start: str = Query(""),
    end: str = Query(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    selected = resolve_period(period_type, period, start, end)
    data = dashboard.build_dashboard(db, selected)

    context = build_period_context(selected, "/")
    context.update(
        {
            "page_name": "dashboard",
            **data,
            "flash": request.query_params.get("flash"),
        }
    )

    return templates.TemplateResponse(request, "dashboard.html", context)
