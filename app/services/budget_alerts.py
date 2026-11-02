"""Budget alert notification service."""

from sqlalchemy.orm import Session
from sqlalchemy import select
from aiogram import Bot

from app.models import Budget
from app.services import ledger
from app.services.money import format_idr


def _reset_alerts_if_needed(db: Session, budget: Budget, period: str) -> None:
    """Reset alert flags if period changed."""
    if budget.period != period:
        budget.alert_70_sent = False
        budget.alert_90_sent = False


async def check_and_send_alerts(db: Session, bot: Bot, chat_id: int, period: str) -> None:
    """Check budget thresholds and send Telegram alerts if needed (async for bot)."""
    progress = ledger.budget_progress(db, period)
    
    for item in progress:
        budget = db.get(Budget, item["id"])
        if not budget:
            continue
        
        _reset_alerts_if_needed(db, budget, period)
        
        pct = item["pct"]
        
        # Alert untuk setiap 10% mulai dari 60%
        if pct >= 100 and not budget.alert_90_sent:
            await bot.send_message(
                chat_id,
                f"🚨 <b>Budget {item['name']} sudah {pct}%!</b>\n"
                f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                f"Over budget: {format_idr(item['spent'] - item['amount'])}",
                parse_mode="HTML"
            )
            budget.alert_90_sent = True
            db.commit()
        elif pct >= 90 and not budget.alert_90_sent:
            await bot.send_message(
                chat_id,
                f"⚠️ <b>Budget {item['name']} sudah {pct}%!</b>\n"
                f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                f"Sisa: {format_idr(item['remaining'])}",
                parse_mode="HTML"
            )
            budget.alert_90_sent = True
            db.commit()
        elif pct >= 80 and not budget.alert_70_sent:
            await bot.send_message(
                chat_id,
                f"⚡ <b>Budget {item['name']} sudah {pct}%</b>\n"
                f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                f"Sisa: {format_idr(item['remaining'])}",
                parse_mode="HTML"
            )
            budget.alert_70_sent = True
            db.commit()
        elif pct >= 70 and not budget.alert_70_sent:
            await bot.send_message(
                chat_id,
                f"💡 <b>Budget {item['name']} sudah {pct}%</b>\n"
                f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                f"Sisa: {format_idr(item['remaining'])}",
                parse_mode="HTML"
            )
            budget.alert_70_sent = True
            db.commit()
        elif pct >= 60 and not budget.alert_70_sent:
            await bot.send_message(
                chat_id,
                f"📊 <b>Budget {item['name']} sudah {pct}%</b>\n"
                f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                f"Sisa: {format_idr(item['remaining'])}",
                parse_mode="HTML"
            )
            budget.alert_70_sent = True
            db.commit()


def send_alert_if_needed(db: Session, bot_token: str, chat_id: int, period: str) -> None:
    """Check and send alerts synchronously (for web transactions)."""
    import asyncio
    from aiogram import Bot
    
    progress = ledger.budget_progress(db, period)
    bot = Bot(token=bot_token)
    
    async def _send():
        for item in progress:
            budget = db.get(Budget, item["id"])
            if not budget:
                continue
            
            _reset_alerts_if_needed(db, budget, period)
            
            pct = item["pct"]
            
            # Alert untuk setiap 10% mulai dari 60%
            if pct >= 100 and not budget.alert_90_sent:
                await bot.send_message(
                    chat_id,
                    f"🚨 <b>Budget {item['name']} sudah {pct}%!</b>\n"
                    f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                    f"Over budget: {format_idr(item['spent'] - item['amount'])}",
                    parse_mode="HTML"
                )
                budget.alert_90_sent = True
                db.commit()
            elif pct >= 90 and not budget.alert_90_sent:
                await bot.send_message(
                    chat_id,
                    f"⚠️ <b>Budget {item['name']} sudah {pct}%!</b>\n"
                    f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                    f"Sisa: {format_idr(item['remaining'])}",
                    parse_mode="HTML"
                )
                budget.alert_90_sent = True
                db.commit()
            elif pct >= 80 and not budget.alert_70_sent:
                await bot.send_message(
                    chat_id,
                    f"⚡ <b>Budget {item['name']} sudah {pct}%</b>\n"
                    f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                    f"Sisa: {format_idr(item['remaining'])}",
                    parse_mode="HTML"
                )
                budget.alert_70_sent = True
                db.commit()
            elif pct >= 70 and not budget.alert_70_sent:
                await bot.send_message(
                    chat_id,
                    f"💡 <b>Budget {item['name']} sudah {pct}%</b>\n"
                    f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                    f"Sisa: {format_idr(item['remaining'])}",
                    parse_mode="HTML"
                )
                budget.alert_70_sent = True
                db.commit()
            elif pct >= 60 and not budget.alert_70_sent:
                await bot.send_message(
                    chat_id,
                    f"📊 <b>Budget {item['name']} sudah {pct}%</b>\n"
                    f"Terpakai: {format_idr(item['spent'])} dari {format_idr(item['amount'])}\n"
                    f"Sisa: {format_idr(item['remaining'])}",
                    parse_mode="HTML"
                )
                budget.alert_70_sent = True
                db.commit()
        await bot.session.close()
    
    # Run in event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send())
        else:
            loop.run_until_complete(_send())
    except RuntimeError:
        asyncio.run(_send())
