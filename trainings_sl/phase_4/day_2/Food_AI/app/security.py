import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .schemas import SignupRequest

hasher = PasswordHasher()
basic = HTTPBasic()
_dummy_hash = hasher.hash(secrets.token_urlsafe(24))


def register_user(db: Session, data: SignupRequest):
    user = User(username=data.username, password_hash=hasher.hash(data.password), role="user")
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.scalar(select(User.id).where(User.username == data.username)) is not None:
            raise HTTPException(409, "Username is already taken") from exc
        raise
    return user


def current_user(credentials: HTTPBasicCredentials = Depends(basic), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == credentials.username))
    try:
        valid = hasher.verify(user.password_hash if user else _dummy_hash, credentials.password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not user or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return user


def admin_user(user: User = Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user
