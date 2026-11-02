"""Reset atau hapus user account."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.db import SessionLocal
from app.models import User, UserSession, LoginAttempt


def list_users():
    with SessionLocal() as db:
        users = db.scalars(select(User)).all()
        if not users:
            print("Tidak ada user.")
            return
        
        print("\nDaftar user:")
        for u in users:
            print(f"  ID: {u.id}, Username: {u.username}, Created: {u.created_at}")


def delete_user(username: str):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            print(f"User {username} tidak ditemukan.")
            return
        
        # Delete related data
        sessions = db.scalars(select(UserSession).where(UserSession.user_id == user.id)).all()
        for s in sessions:
            db.delete(s)
        
        attempts = db.scalars(select(LoginAttempt).where(LoginAttempt.identifier == username)).all()
        for a in attempts:
            db.delete(a)
        
        db.delete(user)
        db.commit()
        print(f"User {username} berhasil dihapus (termasuk {len(sessions)} session dan {len(attempts)} login attempts).")


def delete_all_users():
    with SessionLocal() as db:
        users = db.scalars(select(User)).all()
        count = len(users)
        
        for u in users:
            sessions = db.scalars(select(UserSession).where(UserSession.user_id == u.id)).all()
            for s in sessions:
                db.delete(s)
            db.delete(u)
        
        db.execute(select(LoginAttempt))
        attempts = db.scalars(select(LoginAttempt)).all()
        for a in attempts:
            db.delete(a)
        
        db.commit()
        print(f"Semua {count} user dan data terkait berhasil dihapus.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/reset_user.py list")
        print("  python scripts/reset_user.py delete <username>")
        print("  python scripts/reset_user.py delete-all")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "list":
        list_users()
    elif cmd == "delete" and len(sys.argv) == 3:
        delete_user(sys.argv[2])
    elif cmd == "delete-all":
        confirm = input("Yakin mau hapus SEMUA user? Ketik 'yes': ")
        if confirm == "yes":
            delete_all_users()
        else:
            print("Dibatalkan.")
    else:
        print("Command tidak valid.")
