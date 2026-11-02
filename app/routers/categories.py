"""CRUD kategori via web API."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, Transaction, Account, category_color
from app.security import require_user
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
    """Hapus kategori."""
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Kategori tidak ditemukan")
    
    # Check if used
    usage_count = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.category_id == category_id,
            Transaction.deleted_at.is_(None)
        )
    )
    
    if usage_count > 0:
        raise HTTPException(
            400, 
            f"Kategori {category.name} digunakan di {usage_count} transaksi. Hapus atau ubah transaksi dulu."
        )
    
    db.delete(category)
    db.commit()
    
    return {"success": True}


@router.post("/api/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """Import transaksi dari CSV file."""
    import csv
    from io import StringIO
    from datetime import datetime
    
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(400, "File harus format CSV")
    
    # Read file
    content = await file.read()
    try:
        text = content.decode('utf-8-sig')
    except:
        text = content.decode('latin-1')
    
    # Parse CSV
    reader = csv.reader(StringIO(text))
    rows = list(reader)
    
    if len(rows) < 2:
        raise HTTPException(400, "File CSV kosong atau tidak valid")
    
    header = [h.strip().lower() for h in rows[0]]
    data_rows = rows[1:]
    
    # Auto-detect columns
    col_map = {}
    for idx, h in enumerate(header):
        if any(w in h for w in ['tanggal', 'date', 'tgl', 'waktu']):
            col_map['date'] = idx
        elif any(w in h for w in ['nominal', 'amount', 'jumlah', 'total']):
            col_map['amount'] = idx
        elif any(w in h for w in ['kategori', 'category', 'cat']):
            col_map['category'] = idx
        elif any(w in h for w in ['merchant', 'toko', 'tempat', 'keterangan', 'deskripsi']):
            col_map['merchant'] = idx
        elif any(w in h for w in ['dompet', 'account', 'wallet', 'akun']):
            col_map['account'] = idx
    
    if 'amount' not in col_map:
        raise HTTPException(400, "Kolom nominal tidak ditemukan")
    
    # Load categories dan accounts
    categories_db = {c.name.lower(): c for c in db.scalars(select(Category)).all()}
    accounts_db = {a.name.lower(): a for a in db.scalars(select(Account)).all()}
    
    default_account = db.scalar(select(Account).limit(1))
    if not default_account:
        raise HTTPException(400, "Tidak ada akun. Buat akun dulu.")
    
    imported = 0
    errors = 0
    
    for row_idx, row in enumerate(data_rows, start=2):
        if len(row) < len(col_map):
            errors += 1
            continue
        
        try:
            # Parse amount
            amount_str = row[col_map['amount']].strip().replace(',', '').replace('.', '')
            amount = int(''.join(filter(str.isdigit, amount_str)))
            
            if amount <= 0:
                errors += 1
                continue
            
            # Parse date
            occurred_at = None
            if 'date' in col_map:
                date_str = row[col_map['date']].strip()
                for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d']:
                    try:
                        occurred_at = datetime.strptime(date_str, fmt)
                        break
                    except:
                        continue
            
            if not occurred_at:
                occurred_at = datetime.now()
            
            # Parse category
            category_id = None
            if 'category' in col_map and row[col_map['category']].strip():
                cat_name = row[col_map['category']].strip().lower()
                if cat_name in categories_db:
                    category_id = categories_db[cat_name].id
                else:
                    # Auto-create category
                    new_cat = Category(name=row[col_map['category']].strip().title(), kind='expense')
                    db.add(new_cat)
                    db.flush()
                    category_id = new_cat.id
                    categories_db[cat_name] = new_cat
            
            # Parse account
            account_id = default_account.id
            if 'account' in col_map and row[col_map['account']].strip():
                acc_name = row[col_map['account']].strip().lower()
                if acc_name in accounts_db:
                    account_id = accounts_db[acc_name].id
            
            # Parse merchant
            merchant = None
            if 'merchant' in col_map and row[col_map['merchant']].strip():
                merchant = row[col_map['merchant']].strip()
            
            # Create transaction
            transaction = Transaction(
                kind='expense',
                amount=amount,
                account_id=account_id,
                category_id=category_id,
                merchant=merchant,
                occurred_at=occurred_at,
                source='web_import',
                status='confirmed'
            )
            
            db.add(transaction)
            imported += 1
            
        except Exception:
            errors += 1
    
    db.commit()
    
    return {
        "success": True,
        "imported": imported,
        "errors": errors
    }
