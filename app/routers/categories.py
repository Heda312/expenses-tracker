"""CRUD kategori via web API."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, category_color
from app.security import require_user
from app.services import cleanup, importer
from app.templating import templates

router = APIRouter()


@router.get("/categories")
def categories_page(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """Halaman manage kategori."""
    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            "page_name": "categories",
            "user": user,
        }
    )


@router.get("/api/categories")
def list_categories(
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """List semua kategori."""
    categories = db.scalars(select(Category).order_by(Category.kind, Category.sort_order, Category.name)).all()
    
    return {
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "kind": c.kind,
                "color": c.color,
                "sort_order": c.sort_order,
            }
            for c in categories
        ]
    }


@router.post("/api/categories")
def create_category(
    name: str = Form(...),
    kind: str = Form("expense"),
    color: str = Form(None),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """Buat kategori baru."""
    if kind not in ["expense", "income"]:
        raise HTTPException(400, "kind harus expense atau income")
    
    # Check duplicate
    existing = db.scalar(select(Category).where(Category.name == name))
    if existing:
        raise HTTPException(400, f"Kategori {name} sudah ada")
    
    # Get max sort_order
    max_order = db.scalar(select(func.max(Category.sort_order))) or 0
    
    # Default color: stable random based on name
    if not color or color == "#34d399":
        color = category_color(name)
    
    category = Category(
        name=name,
        kind=kind,
        color=color,
        sort_order=max_order + 1
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    
    return {
        "id": category.id,
        "name": category.name,
        "kind": category.kind,
        "color": category.color,
    }


@router.put("/api/categories/{category_id}")
def update_category(
    category_id: int,
    name: str = Form(None),
    color: str = Form(None),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """Update kategori."""
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Kategori tidak ditemukan")
    
    if name:
        # Check duplicate
        existing = db.scalar(select(Category).where(Category.name == name, Category.id != category_id))
        if existing:
            raise HTTPException(400, f"Kategori {name} sudah ada")
        category.name = name
    
    if color:
        category.color = color
    
    db.commit()
    db.refresh(category)
    
    return {
        "id": category.id,
        "name": category.name,
        "kind": category.kind,
        "color": category.color,
    }


@router.delete("/api/categories/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """Hapus kategori.

    Transaksi aktif masih dilindungi. Kalau kategori hanya dipakai transaksi
    yang sudah dihapus, referensinya dilepas supaya kategori bisa dihapus.
    """
    result = cleanup.delete_category(db, category_id)
    if not result.deleted:
        if result.reason == "notfound":
            raise HTTPException(404, "Kategori tidak ditemukan")
        raise HTTPException(
            400,
            f"Kategori dipakai di {result.active_transactions} transaksi aktif. "
            "Hapus atau ubah transaksinya dulu.",
        )

    return {"success": True}


@router.post("/api/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """Import transaksi dari CSV.

    Dompet yang disebut di file otomatis dibuat, lalu transaksi dihubungkan
    ke dompet tersebut. Setelah import, saldo semua dompet dihitung ulang
    dari transaksi sehingga langsung sinkron.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File harus format CSV")

    content = await file.read()
    result = importer.import_csv(db, content, source="web_import")

    if result.imported == 0:
        raise HTTPException(400, "; ".join(result.messages) or "Import gagal")

    return result.to_dict()
