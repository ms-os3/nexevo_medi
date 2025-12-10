import os
import time
import base64
import hashlib
from fastapi import APIRouter, Request, HTTPException, Depends , Header
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from db import upsert_abha_link, get_abha_link, update_abha_link, log_event, supabase
from secure import encrypt_value, decrypt_value


router = APIRouter()

# env vars
ABHA_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
ABHA_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
ABHA_AUTHORIZE_URL = os.getenv("ABHA_AUTHORIZE_URL", "https://dev.ndhm.gov.in/devservice/gateway/authorize")
ABHA_TOKEN_URL = os.getenv("ABHA_TOKEN_URL", "https://dev.ndhm.gov.in/devservice/gateway/token")
REDIRECT_URI = os.getenv("ABHA_REDIRECT_URI", "http://localhost:8000/abha/callback")
API_KEY = os.getenv("MYAPIKEY")
security = HTTPBasic()

if not ABHA_CLIENT_ID or not ABHA_CLIENT_SECRET:
    raise RuntimeError("Set ABHA_CLIENT_ID and ABHA_CLIENT_SECRET")


# Client id/secret auth for EMR systems

async def authenticate_emr_client(credentials: HTTPBasicCredentials = Depends(security)):
    response = supabase.table("emr_clients").select("*").eq("client_id", credentials.username).execute()
    clients = response.data
    if not clients or clients[0]["client_secret"] != credentials.password:
        raise HTTPException(status_code=401, detail="Invalid client credentials")
    return clients[0]  # includes UUID emr_client.id

# minimal Config for Authlib
config = Config(environ={
    "ABHA_CLIENT_ID": ABHA_CLIENT_ID,
    "ABHA_CLIENT_SECRET": ABHA_CLIENT_SECRET,
    "ABHA_REDIRECT_URI": REDIRECT_URI
})
oauth = OAuth(config)
oauth.register(
#    name="abha",
#    client_id=ABHA_CLIENT_ID,
 #   client_secret=ABHA_CLIENT_SECRET,
  #  authorize_url=ABHA_AUTHORIZE_URL,
   # access_token_url=ABHA_TOKEN_URL,
    #client_kwargs={"scope": "openid profile"},  # adjust per ABDM docs

    name="abha",   # google dummy authentication for demo
    client_id=ABHA_CLIENT_ID,
    client_secret=ABHA_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile email"}
)

# ---------- PKCE helpers ----------
def generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b"=").decode("utf-8")
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode("utf-8")
    return code_verifier, code_challenge

# ---------- refresh token automatically ----------
async def get_valid_access_token(emr_patient_id: str) -> str:
    rec = get_abha_link(emr_patient_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Not linked")

    expires_at = rec.get("expires_at", 0)
    now = int(time.time())

    # If token is still valid and won't expire within 5 minutes, return decrypted token
    if expires_at > now + 300:
        try:
            return decrypt_value(rec["access_token"])
        except Exception:
            raise HTTPException(status_code=500, detail="Token decryption error")

    # Token expired or about to expire — refresh now
    refresh_token_encrypted = rec.get("refresh_token")
    if not refresh_token_encrypted:
        raise HTTPException(status_code=401, detail="No refresh token available")

    refresh_token = decrypt_value(refresh_token_encrypted)

    # Use OAuth client to refresh token
    client = oauth.create_client("abha")
    try:
        new_token = await client.fetch_access_token(
            #ABHA_TOKEN_URL, use when using ABDM
            "https://oauth2.googleapis.com/token", # using google dummy auth for demo
            grant_type="refresh_token",
            refresh_token=refresh_token
        )
    except Exception as e:
        # Log refresh failure or handle
        raise HTTPException(status_code=401, detail="Failed to refresh token")

    # Encrypt and update DB
    enc_access = encrypt_value(new_token["access_token"])
    enc_refresh = encrypt_value(new_token.get("refresh_token", refresh_token))
    new_expires_at = int(time.time()) + new_token.get("expires_in", 3600)

    update_abha_link(emr_patient_id, {
        "access_token": enc_access,
        "refresh_token": enc_refresh,
        "expires_at": new_expires_at
    })

    log_event("abha_token_refreshed", emr_patient_id, {"expires_at": new_expires_at})

    return new_token["access_token"]

# 1) Start linking: redirect user to ABHA auth with PKCE
@router.get("/link/{emr_patient_id}")
async def link_abha(emr_patient_id: str, request: Request, emr_client=Depends(authenticate_emr_client)):
    code_verifier, code_challenge = generate_pkce_pair()
    # store code_verifier temporarily (in production: DB or secure cookie)
    # For hackathon: store in memory keyed by state (or better: store in Supabase 'abha_links' row as temp)
    state = emr_patient_id  # simple; you can prefix with random nonce for more safety
    # We'll pass PKCE challenge via 'code_challenge' param—Authlib supports custom params

    # store verifier in Supabase temporary record
    upsert_abha_link({
        "emr_patient_id": emr_patient_id,
        "access_token": "",
        "refresh_token": "",
        "abha_id": None,
        "expires_at": None,
        "code_verifier_temp": code_verifier,
        "emr_client_id": emr_client["id"]
    })
    # store code_verifier in-memory map for demo (replace with DB + TTL in production)
    log_event("abha_link_started", emr_patient_id, {"method": "PKCE"})

    redirect = await oauth.abha.authorize_redirect(
        request,
        REDIRECT_URI,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method="S256"
    )
    return redirect

# 2) Callback — exchange code (use stored verifier)
@router.get("/callback")
async def callback(request: Request, emr_client=Depends(authenticate_emr_client)):
    try:
        # authlib will parse code from request
        state = request.query_params.get("state")
        if not state:
            raise HTTPException(status_code=400, detail="Missing state")
        # retrieve code_verifier (demo: from request.session)
        code_verifier = None
        rec = get_abha_link(state)
        code_verifier = rec.get("code_verifier_temp") if rec else None

        # If not found in session, try fetch from DB or reject
        if not code_verifier:
            # fallback: in production, fetch from secure store; for demo, throw error
            raise HTTPException(status_code=400, detail="Missing PKCE verifier; complete/restart flow from same browser")
        token = await oauth.abha.authorize_access_token(request, code_verifier=code_verifier)

        # import json, sys
        # print("TOKEN RESPONSE:", json.dumps(token, indent=2), file=sys.stderr, flush=True)
        # # token likely contains id_token / access_token. ABDM may place ABHA in id_token/sub or payload
        #Using google dummy auth for demo

        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        expires_at = int(time.time()) + token.get("expires_in", 3600)
        
        userinfo = token.get("userinfo")

# If userinfo isn’t there, fall back to userinfo endpoint
        if not userinfo:
            client = oauth.create_client("abha")
            userinfo = await client.userinfo()


        # 🔄 Re-map Google identity to your schema
        emr_patient_id = state  # use Google display name
        abha_id = userinfo.get("email") if userinfo else None        # use Google email
        # encrypt tokens
        enc_access = encrypt_value(access_token) if access_token else ""
        enc_refresh = encrypt_value(refresh_token) if refresh_token else ""
        # fetch ABHA id from token or call ABHA profile endpoint
        # abha_id = None
        # id_token = token.get("id_token")
        # if id_token:
        #     # id_token is JWT — parse to get sub (or use userinfo endpoint)
        #     # For demo: do a naive parse (do not trust without signature verify in production)
        #     try:
        #         payload = id_token.split(".")[1] + "=="
        #         import base64, json
        #         padded = base64.b64decode(payload + "="*((4-len(payload)%4)%4))
        #         data = json.loads(padded)
        #         abha_id = data.get("sub") or data.get("abha")
        #     except Exception:
        #         abha_id = None

        # encrypt tokens
       # enc_access = encrypt_value(access_token) if access_token else ""
       # enc_refresh = encrypt_value(refresh_token) if refresh_token else ""
        existing_link = get_abha_link(emr_patient_id)
        if not existing_link:
            raise HTTPException(status_code=404, detail="Link record not found")
        upsert_abha_link({
            #"emr_patient_id": state, --- IGNORE ---, using google name as ehr_patient_id
            "emr_patient_id": emr_patient_id,
            "abha_id": abha_id,
            "access_token": enc_access,
            "refresh_token": enc_refresh,
            "expires_at": expires_at,
            "code_verifier_temp": None,  # ✅ CLEAR verifier after use
            "emr_client_id": emr_client["id"]
        })

        log_event("abha_link_completed",
                #state, --- IGNORE ---, using google name as ehr_patient_id
                emr_patient_id,
                    {
            "abha_id": abha_id,
            "expires_at": expires_at
        })

        # return JSONResponse({"status": "linked", "ehr_patient_id": state, "abha_id": abha_id})
        return JSONResponse({"status": "linked", "emr_patient_id": emr_patient_id, "abha_id": abha_id})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
# 3) Check status (decrypt tokens before returning)
@router.get("/status/{emr_patient_id}")
async def status(emr_patient_id: str, ):
    rec = get_abha_link(emr_patient_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Not linked")
    try:
        rec_out = dict(rec)
        rec_out["access_token"] = decrypt_value(rec_out["access_token"]) if rec_out["access_token"] else ""
        rec_out["refresh_token"] = decrypt_value(rec_out["refresh_token"]) if rec_out["refresh_token"] else ""
        return rec_out
    except Exception:
        raise HTTPException(status_code=500, detail="Decryption error")

# 4) Refresh token
@router.post("/refresh/{emr_patient_id}")
async def refresh(emr_patient_id: str, emr_client=Depends(authenticate_emr_client)):
    rec = get_abha_link(emr_patient_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Not linked")
    refresh_token = decrypt_value(rec["refresh_token"])
    # manual token refresh via Authlib
    client = oauth.create_client("abha")
    # new_token = await client.fetch_access_token(ABHA_TOKEN_URL, grant_type="refresh_token", refresh_token=refresh_token) ---use when using ABDM---
    new_token = await client.fetch_access_token("https://oauth2.googleapis.com/token", grant_type="refresh_token", refresh_token=refresh_token)
    enc_access = encrypt_value(new_token["access_token"])
    enc_refresh = encrypt_value(new_token.get("refresh_token", refresh_token))
    expires_at = int(time.time()) + new_token.get("expires_in", 3600)
    update_abha_link(emr_patient_id, {
        "access_token": enc_access,
        "refresh_token": enc_refresh,
        "expires_at": expires_at
    })

    
    log_event("abha_token_refreshed", emr_patient_id, {
        "expires_at": expires_at
    })

    return {"status": "refreshed", "emr_patient_id": emr_patient_id}


# 5) Audit logs for a patient (for DEV only; secure in production)
@router.get("/audit/{emr_patient_id}")
async def get_audit_log(emr_patient_id: str):
    logs = supabase.table("audit_logs").select("*").eq("emr_patient_id", emr_patient_id).order("timestamp", desc=True).execute()
    return logs.data

