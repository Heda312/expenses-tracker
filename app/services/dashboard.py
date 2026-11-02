"""Agregasi data dashboard untuk periode minggu/bulan/tahun/rentang.

Modul ini tidak menyimpan data apa pun. Semua angka dihitung dari tabel
transaksi dan budget supaya saldo selalu konsisten dengan halaman lain.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Budget, Category, Transaction
from app.services import ledger
from app.services.dates import month_bounds, now_local, to_utc, today_local
from app.services.money import format_idr
from app.services.periods import Period, previous_period

ACTIVE = (Transaction.status == "confirmed", Transaction.deleted_at.is_(None))


def _sum(db: Session, *conditions) -> int:
    value = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(*conditions))
    return int(value or 0)


def _period_summary(db: Session, period: Period) -> dict:
    if period.has_range:
        data = ledger.range_summary(db, period.start, period.end)
    else:
        income = _sum(db, Transaction.kind == "income", *ACTIVE)
        expense = _sum(db, Transaction.kind == "expense", *ACTIVE)
        income_count = db.scalar(
            select(func.count(Transaction.id)).where(Transaction.kind == "income", *ACTIVE)
        ) or 0
        expense_count = db.scalar(
            select(func.count(Transaction.id)).where(Transaction.kind == "expense", *ACTIVE)
        ) or 0
        data = {
            "income": income,
            "expense": expense,
            "net": income - expense,
            "count": int(income_count + expense_count),
            "income_count": int(income_count),
            "expense_count": int(expense_count),
        }

    if period.has_range:
        calendar_days = max((period.end_date - period.start_date).days + 1, 1)
        today = today_local()
        if period.start_date <= today <= period.end_date:
            elapsed_days = (today - period.start_date).days + 1
        else:
            elapsed_days = calendar_days
    else:
        elapsed_days = 1
        first_at = db.scalar(select(func.min(Transaction.occurred_at)).where(*ACTIVE))
        if first_at:
            elapsed_days = max((today_local() - first_at.date()).days + 1, 1)
        calendar_days = elapsed_days

    active_days = db.scalar(
        select(func.count(func.distinct(func.date(Transaction.occurred_at)))).where(
            Transaction.kind != "transfer", *ACTIVE, *(
                [Transaction.occurred_at >= period.start, Transaction.occurred_at < period.end]
                if period.has_range
                else []
            )
        )
    ) or 0

    expense_count = data["expense_count"]
    savings_rate = round(data["net"] / data["income"] * 100) if data["income"] > 0 else None

    return {
        **data,
        "savings_rate": savings_rate,
        "daily_average": round(data["expense"] / elapsed_days) if elapsed_days else 0,
        "calendar_days": calendar_days,
        "elapsed_days": elapsed_days,
        "active_days": int(active_days),
        "average_transaction": round(data["expense"] / expense_count) if expense_count else 0,
        "has_data": bool(data["income"] or data["expense"] or data["count"]),
    }


def _comparison(db: Session, period: Period, current: dict) -> dict | None:
    prev = previous_period(period)
    if prev is None or not prev.has_range:
        return None

    if prev.has_range:
        data = ledger.range_summary(db, prev.start, prev.end)
    else:
        return None

    def change(current_value: int, previous_value: int) -> int | None:
        if previous_value <= 0:
            return None
        return round((current_value - previous_value) / previous_value * 100)

    return {
        "label": prev.label,
        "income": data["income"],
        "expense": data["expense"],
        "net": data["net"],
        "income_change_pct": change(current["income"], data["income"]),
        "expense_change_pct": change(current["expense"], data["expense"]),
        "net_change": current["net"] - data["net"],
    }


def _months_in_range(start_date: date, end_date: date) -> list[str]:
    months: list[str] = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return months


def _budget_months(period: Period) -> list[str]:
    if period.type == "month":
        return [period.key]
    if period.type == "week" and period.start_date:
        return [period.start_date.strftime("%Y-%m")]
    if period.type == "year" and period.start_date and period.end_date:
        return [f"{period.start_date.year:04d}-{month:02d}" for month in range(1, 13)]
    if period.type == "custom" and period.start_date and period.end_date:
        return _months_in_range(period.start_date, period.end_date)
    return [now_local().strftime("%Y-%m")]


def _budget_totals(db: Session, period: Period) -> dict:
    # Budget disimpan per bulan. Untuk periode panjang, budget bulan-bulan
    # yang tercakup dijumlahkan supaya tetap bisa dibandingkan dengan belanja.
    budget_range = period
    if period.is_all:
        months = [now_local().strftime("%Y-%m")]
        start, end = month_bounds(months[0])
        today = today_local()
        budget_range = Period(
            "month",
            months[0],
            start,
            end,
            today.replace(day=1),
            today,
            "Bulan ini",
        )
    else:
        months = _budget_months(period)

    budgets = db.scalars(
        select(Budget)
        .options(joinedload(Budget.category))
        .where(Budget.period.in_(months))
    ).all()

    grouped: dict[int, dict] = {}
    for budget in budgets:
        category = budget.category
        if category is None:
            continue
        item = grouped.setdefault(
            budget.category_id,
            {
                "category_id": budget.category_id,
                "name": category.name,
                "color": category.color or "#64748b",
                "amount": 0,
                "spent": 0,
            },
        )
        item["amount"] += int(budget.amount or 0)

    if not grouped:
        return {
            "rows": [],
            "total": 0,
            "spent": 0,
            "remaining": 0,
            "pct": None,
            "over_count": 0,
            "months": months,
            "has_budget": False,
            "reference_label": budget_range.label,
        }

    spent_conditions = [
        Transaction.kind == "expense",
        Transaction.category_id.in_(list(grouped)),
        *ACTIVE,
    ]
    if budget_range.has_range:
        spent_conditions += [
            Transaction.occurred_at >= budget_range.start,
            Transaction.occurred_at < budget_range.end,
        ]

    spent_rows = db.execute(
        select(Transaction.category_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(*spent_conditions)
        .group_by(Transaction.category_id)
    ).all()
    spent_by_category = {row[0]: int(row[1] or 0) for row in spent_rows}

    items = []
    for item in grouped.values():
        spent = spent_by_category.get(item["category_id"], 0)
        amount = item["amount"]
        pct = round(spent / amount * 100) if amount else 0
        items.append(
            {
                **item,
                "spent": spent,
                "remaining": amount - spent,
                "pct": pct,
                "over": spent > amount,
            }
        )

    items.sort(key=lambda item: item["spent"], reverse=True)
    total = sum(item["amount"] for item in items)
    spent = sum(item["spent"] for item in items)
    return {
        "rows": items,
        "total": total,
        "spent": spent,
        "remaining": total - spent,
        "pct": round(spent / total * 100) if total else None,
        "over_count": sum(1 for item in items if item["over"]),
        "months": months,
        "has_budget": True,
        "reference_label": budget_range.label,
    }


def _health_score(summary: dict, budget: dict) -> dict:
    if not summary["has_data"]:
        return {
            "score": 0,
            "grade": "Belum ada data",
            "color": "muted",
            "emoji": "📊",
            "breakdown": {
                "budget_discipline": 0,
                "savings_ability": 0,
                "income_health": 0,
                "expense_control": 0,
            },
        }

    income = summary["income"]
    expense = summary["expense"]
    savings_rate = summary["savings_rate"] or 0

    savings_score = min(100, max(0, round(savings_rate * 2)))
    income_score = 100 if income > 0 else 0
    if income <= 0:
        control_score = 0
    elif expense <= income:
        control_score = 100
    else:
        control_score = max(0, round(100 - (expense - income) / income * 100))

    if budget["has_budget"] and budget["rows"]:
        over_ratio = budget["over_count"] / len(budget["rows"])
        usage = budget["pct"] or 0
        budget_score = max(0, round(100 - over_ratio * 100 - max(0, usage - 100) * 0.5))
    else:
        budget_score = 50  # netral kalau belum ada budget

    overall = round(
        budget_score * 0.3
        + savings_score * 0.3
        + income_score * 0.2
        + control_score * 0.2
    )

    if overall >= 80:
        grade, color, emoji = "Sangat Baik", "income", "💚"
    elif overall >= 60:
        grade, color, emoji = "Baik", "accent", "💙"
    elif overall >= 40:
        grade, color, emoji = "Cukup", "warn", "💛"
    else:
        grade, color, emoji = "Perlu Perbaikan", "expense", "❤️"

    return {
        "score": overall,
        "grade": grade,
        "color": color,
        "emoji": emoji,
        "breakdown": {
            "budget_discipline": budget_score,
            "savings_ability": savings_score,
            "income_health": income_score,
            "expense_control": control_score,
        },
    }


def _insights(summary: dict, comparison: dict | None, budget: dict, categories: list[dict]) -> list[dict]:
    insights: list[dict] = []

    if not summary["has_data"]:
        return [
            {
                "icon": "📭",
                "tone": "muted",
                "title": "Belum ada transaksi",
                "text": "Tambahkan transaksi atau pilih periode lain untuk melihat insight.",
            }
        ]

    net = summary["net"]
    if net > 0:
        rate = summary["savings_rate"]
        text = f"Pemasukan lebih besar {format_idr(net)}"
        if rate is not None:
            text += f" dengan rasio tabungan {rate}%"
        insights.append({"icon": "💚", "tone": "positive", "title": "Arus kas surplus", "text": text})
    elif net < 0:
        insights.append(
            {
                "icon": "⚠️",
                "tone": "danger",
                "title": "Arus kas defisit",
                "text": f"Pengeluaran melebihi pemasukan sebesar {format_idr(abs(net))}.",
            }
        )
    else:
        insights.append(
            {
                "icon": "⚖️",
                "tone": "info",
                "title": "Arus kas seimbang",
                "text": "Pemasukan dan pengeluaran sama besar pada periode ini.",
            }
        )

    if summary["income"] == 0 and summary["expense"] > 0:
        insights.append(
            {
                "icon": "📥",
                "tone": "warning",
                "title": "Pemasukan belum tercatat",
                "text": "Ada pengeluaran, tetapi belum ada pemasukan pada periode ini.",
            }
        )

    if comparison and comparison["expense_change_pct"] is not None:
        change = comparison["expense_change_pct"]
        if abs(change) >= 10:
            insights.append(
                {
                    "icon": "📈" if change > 0 else "📉",
                    "tone": "warning" if change > 0 else "positive",
                    "title": f"Pengeluaran {'naik' if change > 0 else 'turun'} {abs(change)}%",
                    "text": (
                        f"Dibanding {comparison['label']}: "
                        f"{format_idr(comparison['expense'])} → {format_idr(summary['expense'])}."
                    ),
                }
            )

    if categories:
        top = categories[0]
        if top["pct"] >= 30:
            insights.append(
                {
                    "icon": "🎯",
                    "tone": "info",
                    "title": f"{top['name']} dominan ({top['pct']}%)",
                    "text": f"Total {format_idr(top['total'])} dari seluruh pengeluaran periode ini.",
                }
            )

    for item in budget["rows"]:
        if item["over"]:
            insights.append(
                {
                    "icon": "🚨",
                    "tone": "danger",
                    "title": f"Budget {item['name']} terlampaui",
                    "text": f"Sudah {format_idr(item['spent'])} dari target {format_idr(item['amount'])}.",
                }
            )
        elif item["pct"] >= 80:
            insights.append(
                {
                    "icon": "⚡",
                    "tone": "warning",
                    "title": f"Budget {item['name']} hampir habis",
                    "text": f"Terpakai {item['pct']}%, sisa {format_idr(item['remaining'])}.",
                }
            )
        if len(insights) >= 6:
            break

    if summary["income"] > 0 and summary["savings_rate"] is not None and summary["savings_rate"] < 20:
        insights.append(
            {
                "icon": "🐷",
                "tone": "warning",
                "title": "Rasio tabungan rendah",
                "text": f"Baru {summary['savings_rate']}% dari pemasukan. Target sehat sekitar 20%.",
            }
        )

    return insights[:6]


def _category_totals(db: Session, period: Period, limit: int = 8) -> list[dict]:
    if period.has_range:
        return ledger.category_totals_range(db, period.start, period.end, kind="expense", limit=limit)
    start = datetime(2000, 1, 1)
    end = to_utc(now_local()) + timedelta(days=1)
    return ledger.category_totals_range(db, start, end, kind="expense", limit=limit)


def build_dashboard(db: Session, period: Period) -> dict:
    """Kumpulkan semua data yang dipakai template dashboard."""
    summary = _period_summary(db, period)
    comparison = _comparison(db, period, summary)
    budget = _budget_totals(db, period)
    categories = _category_totals(db, period)
    health = _health_score(summary, budget)
    insights = _insights(summary, comparison, budget, categories)

    balances = ledger.account_balances(db)
    total_balance = sum(item["balance"] for item in balances)

    cashflow = ledger.cashflow(db, months=6, end_period=period.month_key)
    cashflow_has_data = any(item["income"] or item["expense"] for item in cashflow)

    recent_conditions = [*ACTIVE]
    if period.has_range:
        recent_conditions += [Transaction.occurred_at >= period.start, Transaction.occurred_at < period.end]

    recent = db.scalars(
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account))
        .where(*recent_conditions)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .limit(8)
    ).all()

    return {
        "period": period,
        "summary": summary,
        "comparison": comparison,
        "health": health,
        "budget": budget,
        "insights": insights,
        "categories": categories,
        "donut": ledger.donut_segments(categories),
        "balances": balances,
        "total_balance": total_balance,
        "cashflow": cashflow,
        "cashflow_has_data": cashflow_has_data,
        "recent": recent,
        "budget_month_key": period.month_key,
    }
