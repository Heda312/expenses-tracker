"""Perintah baris perintah.

Contoh:
    python -m app.cli create-user --username saya
    python -m app.cli seed
"""

import argparse
import secrets
import string

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from app.seed import ensure_seed


def _gen_password() -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(16))


def create_user(username: str, password: str | None) -> None:
    username = username.strip().lower()
    if not password:
        password = _gen_password()
        print(f"Password di-generate: {password}")

    if len(password) < 12:
        raise SystemExit("Password minimal 12 karakter.")

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("Username sudah terdaftar.")

        db.add(User(username=username, password_hash=hash_password(password)))
        db.commit()

    print(f"User dibuat: {username}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Utilitas Catat")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="Buat akun untuk login")
    create.add_argument("--username", required=True)
    create.add_argument("--password", default=None)

    sub.add_parser("seed", help="Isi kategori dan dompet default")

    args = parser.parse_args()

    if args.command == "create-user":
        create_user(args.username, args.password)
    elif args.command == "seed":
        with SessionLocal() as db:
            ensure_seed(db)
        print("Seed selesai.")


if __name__ == "__main__":
    main()
