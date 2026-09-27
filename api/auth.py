"""
Authentication router for Signalwave.

Two distinct OAuth flows live here:

1. SIGN-IN OAUTH (Google / Facebook login to Signalwave itself)
   /auth/google/start        → redirect to Google consent screen
   /auth/google/callback     → exchange code → find/create User → JWT → redirect to frontend
   /auth/facebook/start      → redirect to Facebook login dialog
   /auth/facebook/callback   → same pattern

2. ACCOUNT-CONNECTION OAUTH (linking a social media account to monitor)
   /auth/meta/connect/start     → redirect to Meta with pages+comments scopes
   /auth/meta/connect/callback  → store long-lived token in PlatformAppCredential
                                  → return list of pages+IG accounts to frontend
   /auth/youtube/connect/start  → redirect to Google with youtube.force-ssl scope
   /auth/youtube/connect/callback → store OAuth token → return channel list

3. EMAIL/PASSWORD
   POST /auth/register   → create User with bcrypt password
   POST /auth/login      → verify → JWT
   GET  /auth/me         → return current user from JWT
"""
import os
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)  # always reload .env so FRONTEND_URL etc. are fresh

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from loguru import logger
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import User, Client, PlatformAppCredential, Platform

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Config ─────────────────────────────────────────────────────
JWT_SECRET      = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_DAYS = 30

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

FACEBOOK_APP_ID     = os.getenv("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
FACEBOOK_LOGIN_CONFIG_ID = os.getenv("FACEBOOK_LOGIN_CONFIG_ID", "").strip()

# Meta scopes for ACCOUNT CONNECTION (not login)
# TEMP (testing): keep only minimal page scopes.
# Re-enable advanced scopes after connection flow is confirmed working.
META_CONNECT_SCOPES = (
    "pages_show_list,"
    "pages_read_engagement"
)

# YouTube scopes for ACCOUNT CONNECTION
YOUTUBE_CONNECT_SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly "
    "https://www.googleapis.com/auth/youtube.force-ssl"
)

FRONTEND_URL  = os.getenv("FRONTEND_URL", "http://localhost:9000")   # GitHub Pages URL in prod
BACKEND_URL   = os.getenv("BACKEND_URL", "http://localhost:9000")    # Render URL in prod

GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v21.0")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# In-memory state store for CSRF protection (replace with Redis in production)
_oauth_states: dict[str, dict] = {}


# ── JWT helpers ────────────────────────────────────────────────

def _create_jwt(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _decode_jwt(token: str) -> int:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    return int(payload["sub"])


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency — validates Bearer token and returns the User."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth[7:]
    try:
        user_id = _decode_jwt(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalid or expired")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


# ── Helpers ────────────────────────────────────────────────────

def _get_or_create_user(
    db: Session,
    *,
    email: str,
    name: str,
    avatar_url: str = "",
    google_id: str = None,
    facebook_id: str = None,
) -> User:
    """
    Find an existing user by email or social ID, or create a new one.
    Also creates a matching Client record if one doesn't exist.
    """
    # Try by social ID first
    user = None
    if google_id:
        user = db.query(User).filter_by(google_id=google_id).first()
    if not user and facebook_id:
        user = db.query(User).filter_by(facebook_id=facebook_id).first()
    if not user:
        user = db.query(User).filter_by(email=email).first()

    if user:
        # Update any missing social IDs
        if google_id and not user.google_id:
            user.google_id = google_id
        if facebook_id and not user.facebook_id:
            user.facebook_id = facebook_id
        if not user.name and name:
            user.name = name
        if not user.avatar_url and avatar_url:
            user.avatar_url = avatar_url
    else:
        # New user — create User + Client in one transaction
        user = User(
            email=email, name=name, avatar_url=avatar_url,
            google_id=google_id, facebook_id=facebook_id,
        )
        db.add(user)
        db.flush()   # get user.id without committing

        client = Client(
            name=name,
            contact_email=email,
        )
        db.add(client)
        db.flush()

        user.client_id = client.id

    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def _redirect_with_token(user: User, is_new: bool = False) -> RedirectResponse:
    """After successful OAuth, redirect the browser to the frontend with a JWT."""
    token = _create_jwt(user.id)
    dest = "onboarding.html" if is_new else "dashboard.html"
    url = f"{FRONTEND_URL}/{dest}?token={token}"
    return RedirectResponse(url=url, status_code=302)


# ══════════════════════════════════════════════════════════════
# 1. EMAIL / PASSWORD
# ══════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=req.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if len(req.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    hashed = pwd_context.hash(req.password)
    user = User(
        email=req.email,
        name=req.name or req.email.split("@")[0],
        hashed_password=hashed,
        last_login_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()

    client = Client(name=user.name, contact_email=req.email)
    db.add(client)
    db.flush()
    user.client_id = client.id
    db.commit()
    db.refresh(user)

    return {"token": _create_jwt(user.id), "user": _user_dict(user)}


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=req.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not pwd_context.verify(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login_at = datetime.utcnow()
    db.commit()
    return {"token": _create_jwt(user.id), "user": _user_dict(user)}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return _user_dict(current_user)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "client_id": user.client_id,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


# ══════════════════════════════════════════════════════════════
# 2. GOOGLE SIGN-IN (login to Signalwave via Google account)
# ══════════════════════════════════════════════════════════════

@router.get("/google/start")
def google_start():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured (GOOGLE_CLIENT_ID missing)")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"provider": "google", "purpose": "login"}

    params = urllib.parse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{BACKEND_URL}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}", status_code=302)


@router.get("/google/callback")
def google_callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    _oauth_states.pop(state, None)

    # Exchange code for tokens
    resp = httpx.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{BACKEND_URL}/auth/google/callback",
        "grant_type": "authorization_code",
    }, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Google token exchange failed: {resp.text}")

    tokens = resp.json()
    access_token = tokens["access_token"]

    # Get user info
    ui = httpx.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    ).json()

    user = _get_or_create_user(
        db,
        email=ui["email"],
        name=ui.get("name", ""),
        avatar_url=ui.get("picture", ""),
        google_id=ui["id"],
    )
    is_new = (user.last_login_at is None or
              (datetime.utcnow() - user.created_at).total_seconds() < 5)
    return _redirect_with_token(user, is_new=is_new)


# ══════════════════════════════════════════════════════════════
# 3. FACEBOOK SIGN-IN (login to Signalwave via Facebook account)
# ══════════════════════════════════════════════════════════════

@router.get("/facebook/start")
def facebook_start():
    if not FACEBOOK_APP_ID:
        raise HTTPException(status_code=501, detail="Facebook OAuth not configured (FACEBOOK_APP_ID missing)")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"provider": "facebook", "purpose": "login"}

    params_dict = {
        "client_id": FACEBOOK_APP_ID,
        "redirect_uri": f"{BACKEND_URL}/auth/facebook/callback",
        "state": state,
        "scope": "email,public_profile",
        "response_type": "code",
    }
    if FACEBOOK_LOGIN_CONFIG_ID:
        params_dict["config_id"] = FACEBOOK_LOGIN_CONFIG_ID
    params = urllib.parse.urlencode(params_dict)
    return RedirectResponse(
        f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?{params}", status_code=302
    )


@router.get("/facebook/callback")
def facebook_callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    _oauth_states.pop(state, None)

    # Exchange code for access token
    resp = httpx.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token",
        params={
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "redirect_uri": f"{BACKEND_URL}/auth/facebook/callback",
            "code": code,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Facebook token exchange failed: {resp.text}")

    access_token = resp.json()["access_token"]

    # Get user info
    ui = httpx.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/me",
        params={"fields": "id,name,email,picture.width(200)", "access_token": access_token},
        timeout=10,
    ).json()

    user = _get_or_create_user(
        db,
        email=ui.get("email", f"fb_{ui['id']}@signalwave.local"),
        name=ui.get("name", ""),
        avatar_url=ui.get("picture", {}).get("data", {}).get("url", ""),
        facebook_id=ui["id"],
    )
    is_new = (datetime.utcnow() - user.created_at).total_seconds() < 5
    return _redirect_with_token(user, is_new=is_new)


# ══════════════════════════════════════════════════════════════
# 4. META ACCOUNT CONNECTION (adding FB Pages / IG to monitor)
#    Different from login — uses pages+comments scopes
# ══════════════════════════════════════════════════════════════

@router.get("/meta/connect/start")
def meta_connect_start(current_user: User = Depends(get_current_user)):
    if not FACEBOOK_APP_ID:
        raise HTTPException(status_code=501, detail="Facebook App not configured")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"provider": "meta", "purpose": "connect", "user_id": current_user.id}

    params_dict = {
        "client_id": FACEBOOK_APP_ID,
        "redirect_uri": f"{BACKEND_URL}/auth/meta/connect/callback",
        "state": state,
        "scope": META_CONNECT_SCOPES,
        "response_type": "code",
    }
    if FACEBOOK_LOGIN_CONFIG_ID:
        params_dict["config_id"] = FACEBOOK_LOGIN_CONFIG_ID
    params = urllib.parse.urlencode(params_dict)
    return {"redirect_url": f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?{params}"}


@router.get("/meta/connect/callback")
def meta_connect_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    state_data = _oauth_states.pop(state, None)
    if not state_data or state_data.get("purpose") != "connect":
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    user_id = state_data["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Exchange code for short-lived token
    resp = httpx.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token",
        params={
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "redirect_uri": f"{BACKEND_URL}/auth/meta/connect/callback",
            "code": code,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        logger.error(f"[Meta] Token exchange failed: {resp.status_code} — {resp.text}")
        raise HTTPException(status_code=502, detail=f"Meta token exchange failed: {resp.text}")

    short_token = resp.json()["access_token"]

    # Exchange for long-lived token (60 days)
    ll_resp = httpx.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "fb_exchange_token": short_token,
        },
        timeout=15,
    )
    long_lived_token = ll_resp.json().get("access_token", short_token)

    # Store credential
    cred = db.query(PlatformAppCredential).filter_by(
        client_id=user.client_id, platform=Platform.FACEBOOK
    ).first()
    if not cred:
        cred = PlatformAppCredential(
            client_id=user.client_id,
            platform=Platform.FACEBOOK,
            fb_app_id=FACEBOOK_APP_ID,
            fb_app_secret=FACEBOOK_APP_SECRET,
        )
        db.add(cred)
    cred.fb_long_lived_token = long_lived_token
    db.commit()

    # Fetch pages this user manages
    try:
        pages_resp = httpx.get(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account{id,name,username}",
                "access_token": long_lived_token,
            },
            timeout=15,
        ).json()
        logger.info(f"[Meta] /me/accounts response: {pages_resp}")
    except Exception as e:
        logger.error(f"[Meta] Failed to fetch pages: {e}")
        pages_resp = {}

    profiles = []
    for page in pages_resp.get("data", []):
        profiles.append({
            "id": page["id"],
            "name": page["name"],
            "platform": "facebook",
            "type": "page",
            "access_token": page.get("access_token", ""),
        })
        ig = page.get("instagram_business_account")
        if ig:
            profiles.append({
                "id": ig["id"],
                "name": ig.get("name") or ig.get("username", ig["id"]),
                "handle": f"@{ig.get('username', '')}",
                "platform": "instagram",
                "type": "instagram",
                "access_token": page.get("access_token", ""),
            })

    logger.info(f"[Meta] Found {len(profiles)} profiles for user {user.id}")

    # Redirect back to onboarding with profiles in session
    token = _create_jwt(user.id)
    profiles_param = urllib.parse.quote_plus(
        __import__("json").dumps(profiles)
    )
    return RedirectResponse(
        f"{FRONTEND_URL}/onboarding.html?token={token}&step=3&profiles={profiles_param}",
        status_code=302,
    )


# ══════════════════════════════════════════════════════════════
# 5. YOUTUBE ACCOUNT CONNECTION
# ══════════════════════════════════════════════════════════════

@router.get("/youtube/connect/start")
def youtube_connect_start(current_user: User = Depends(get_current_user)):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"provider": "youtube", "purpose": "connect", "user_id": current_user.id}

    params = urllib.parse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{BACKEND_URL}/auth/youtube/connect/callback",
        "response_type": "code",
        "scope": YOUTUBE_CONNECT_SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    })
    return {"redirect_url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


@router.get("/youtube/connect/callback")
def youtube_connect_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    state_data = _oauth_states.pop(state, None)
    if not state_data or state_data.get("purpose") != "connect":
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    user_id = state_data["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Exchange code for tokens
    resp = httpx.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{BACKEND_URL}/auth/youtube/connect/callback",
        "grant_type": "authorization_code",
    }, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Google token exchange failed: {resp.text}")

    tokens = resp.json()
    import math
    expiry = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))

    # Store credential
    cred = db.query(PlatformAppCredential).filter_by(
        client_id=user.client_id, platform=Platform.YOUTUBE
    ).first()
    if not cred:
        cred = PlatformAppCredential(
            client_id=user.client_id,
            platform=Platform.YOUTUBE,
            yt_client_id=GOOGLE_CLIENT_ID,
            yt_client_secret=GOOGLE_CLIENT_SECRET,
        )
        db.add(cred)
    cred.yt_access_token  = tokens["access_token"]
    cred.yt_refresh_token = tokens.get("refresh_token", cred.yt_refresh_token)
    cred.yt_token_expiry  = expiry
    db.commit()

    # Fetch channels this user manages
    ch_resp = httpx.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={
            "part": "snippet",
            "mine": "true",
            "maxResults": "20",
        },
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    ).json()

    profiles = []
    for ch in ch_resp.get("items", []):
        sn = ch.get("snippet", {})
        profiles.append({
            "id": ch["id"],
            "name": sn.get("title", ch["id"]),
            "handle": f"@{sn.get('customUrl', '').lstrip('@')}",
            "platform": "youtube",
            "type": "channel",
            "thumbnail": sn.get("thumbnails", {}).get("default", {}).get("url", ""),
        })

    token = _create_jwt(user.id)
    profiles_param = urllib.parse.quote_plus(
        __import__("json").dumps(profiles)
    )
    return RedirectResponse(
        f"{FRONTEND_URL}/onboarding.html?token={token}&step=3&profiles={profiles_param}",
        status_code=302,
    )


# ══════════════════════════════════════════════════════════════
# 6. SAVE SELECTED PROFILE (Step 3 → 4 in onboarding wizard)
# ══════════════════════════════════════════════════════════════

class SaveProfileRequest(BaseModel):
    platform: str          # facebook | instagram | youtube
    channel_id: str
    channel_name: str
    access_token: str
    handle: str = ""


@router.post("/connect/save-profile")
def save_profile(
    req: SaveProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Called by onboarding Step 3 when the user picks a profile to track.
    Creates/updates a MonitoredChannel row.
    """
    from src.db.models import MonitoredChannel

    existing = db.get(MonitoredChannel, req.channel_id)
    if existing:
        existing.access_token = req.access_token
        existing.is_active = True
        db.commit()
        return {"message": "Channel updated", "id": req.channel_id}

    channel = MonitoredChannel(
        id=req.channel_id,
        client_id=current_user.client_id,
        platform=Platform(req.platform),
        name=req.channel_name,
        access_token=req.access_token,
    )
    db.add(channel)
    db.commit()
    return {"message": "Channel added", "id": req.channel_id}

