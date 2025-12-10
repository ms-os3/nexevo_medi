import sqlite3
import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
import json
import requests
import logging
from datetime import datetime
from starlette.middleware.sessions import SessionMiddleware
import os
from auth import router as auth_router
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")  
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

app = FastAPI()
# secret key for session signing
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET_KEY"))


app.include_router(auth_router, prefix="/abha")

@app.get("/")
def read_root():
    return {"message": "Welcome to the NAMASTE Terminology API"}

# DB setup
conn = sqlite3.connect('terminology.db', check_same_thread=False)
logger = logging.getLogger("uvicorn.error")

# Startup: load CSVs
@app.on_event("startup")
def startup_event():
    namaste_df = pd.read_csv('nexevo_medi\\namaste_terms.csv')
    mapped_df = pd.read_csv('nexevo_medi\\mapped_terms.csv')
    tm2_df = pd.read_csv('nexevo_medi\\tm2_entities.csv')
    conn.execute('''CREATE TABLE IF NOT EXISTS biomed_codes (code TEXT PRIMARY KEY, title TEXT, definition TEXT)''')
    namaste_df.to_sql('namaste_terms', conn, if_exists='replace')
    mapped_df.to_sql('mapped_terms', conn, if_exists='replace')
    tm2_df.to_sql('tm2_entities', conn, if_exists='replace')

# 1. CodeSystem
@app.get("/CodeSystem/namaste")
def get_codesystem(_history: str = Query(None, alias="_history")):
    with open('namaste_codesystem.json', 'r', encoding='utf-8') as f:
        cs = json.load(f)
    if _history:
        cs['version'] = _history
    return cs


# 2. ConceptMap
@app.get("/ConceptMap/namaste-tm2")
def get_conceptmap(_history: str = Query(None, alias="_history")):
    with open('namaste_tm2_conceptmap.json', 'r', encoding='utf-8') as f:
        cm = json.load(f)
    if _history:
        cm['version'] = _history
    return cm

# 3. ValueSet expand (autocomplete)
class ValueSetExpandResponse(BaseModel):
    expansion: list[dict]

@app.get("/ValueSet/namaste/$expand", response_model=ValueSetExpandResponse)
def valueset_expand(filter: str = Query(..., min_length=3)):
    query = """
    SELECT n.NAMC_CODE as code, n.NAMC_term as display, m."TM2 Code" as tm2_code, m.Similarity_Score as similarity
    FROM namaste_terms n
    LEFT JOIN mapped_terms m ON n.NAMC_CODE = m.NAMC_CODE
    WHERE n.NAMC_term LIKE ? OR n."NAMC _term_diacritical" LIKE ?
    LIMIT 10
    """
    cursor = conn.cursor()
    cursor.execute(query, (f"%{filter}%", f"%{filter}%"))
    results = cursor.fetchall()
    expansion = [{
        "code": row[0],
        "display": row[1],
        "extension": [
            {"url": "tm2", "valueCode": row[2]},
            {"url": "similarity", "valueDecimal": row[3]}
        ]
    } for row in results]
    return {"expansion": expansion}

# 4. ConceptMap translate
class TranslateRequest(BaseModel):
    code: str
    system: str
    targetsystem: str

@app.post("/ConceptMap/$translate")
def conceptmap_translate(request: TranslateRequest):
    # if request.system == "http://example.org/fhir/CodeSystem/namaste" and request.targetsystem == "http://who.int/icd11/tm2":
    #     query = "SELECT \"TM2 Code\" FROM mapped_terms WHERE NAMC_CODE = ?"
    # elif request.system == "http://who.int/icd11/tm2" and request.targetsystem == "http://example.org/fhir/CodeSystem/namaste":
    #     query = "SELECT NAMC_CODE FROM mapped_terms WHERE \"TM2 Code\" = ?"
    if request.system.lower() == "namaste" and request.targetsystem.lower() == "tm2":
        query = "SELECT \"TM2 Code\" FROM mapped_terms WHERE NAMC_CODE = ?"
    elif request.system.lower() == "tm2" and request.targetsystem.lower() == "namaste":
        query = "SELECT NAMC_CODE FROM mapped_terms WHERE \"TM2 Code\" = ?"
    else:
        raise HTTPException(400, "Unsupported systems")
    cursor = conn.cursor()
    cursor.execute(query, (request.code,))
    result = cursor.fetchone()
    if result:
        return {
            "result": True,
            "match": [{
                "equivalence": "equivalent",
                "concept": {"code": result[0]}
            }]
        }
    raise HTTPException(404, "No mapping found")

# 5. Biomed lookup
@app.get("/CodeSystem/biomed/$lookup")
def biomed_lookup(code: str = Query(...)):
    cursor = conn.cursor()
    cursor.execute("SELECT title, definition FROM biomed_codes WHERE code = ?", (code,))
    result = cursor.fetchone()
    if result:
        return {"code": code, "display": result[0], "definition": result[1]}
    who_token = get_who_token()
    headers = {
        "Authorization": f"Bearer {who_token}",
        "Accept": "application/json",
        "Accept-Language": "en"
    }
    resp = requests.get(f"https://id.who.int/icd/release/11/2024-01/mms/{code}", headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        conn.execute("INSERT OR REPLACE INTO biomed_codes (code, title, definition) VALUES (?, ?, ?)",
                     (code, data.get('title'), data.get('definition')))
        conn.commit()
        return {"code": code, "display": data.get('title'), "definition": data.get('definition')}
    raise HTTPException(404, "Code not found")

def get_who_token():
    client_id = "your_who_client_id"  # Replace with real credentials
    client_secret = "your_who_client_secret"
    resp = requests.post("https://icdaccessmanagement.who.int/connect/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "icdapi_access",
        "grant_type": "client_credentials"
    })
    return resp.json().get("access_token")

# 6. Sync TM2 or other WHO chapters
@app.post("/sync")
def sync_who_data(chapter: str = Query("26", description="e.g., 26 for TM2")):
    who_token = get_who_token()
    headers = {"Authorization": f"Bearer {who_token}", "Accept": "application/json"}
    resp = requests.get(f"https://id.who.int/icd/release/11/2024-01/mms/search?q=chapter:{chapter}", headers=headers)
    if resp.status_code == 200:
        data = resp.json().get('results', [])
        for item in data:
            code = item.get('code')
            title = item.get('title')
            if chapter == "26":
                conn.execute("INSERT OR REPLACE INTO tm2_entities (\"TM2 Code\", Title) VALUES (?, ?)", (code, title))
            else:
                conn.execute("INSERT OR REPLACE INTO biomed_codes (code, title) VALUES (?, ?)", (code, title))
        conn.commit()
        return {"status": "Synced", "count": len(data)}
    raise HTTPException(500, "Sync failed")

# 7. Upload FHIR Bundle
@app.post("/Bundle")
def upload_bundle(bundle: dict):
    # Validate bundle structure
    if bundle.get("resourceType") != "Bundle":
        raise HTTPException(400, "Invalid FHIR Bundle: resourceType must be 'Bundle'")
    
    problems = [entry['resource'] for entry in bundle.get('entry', []) if entry['resource'].get('resourceType') == 'Condition']
    if not problems:
        raise HTTPException(400, "Bundle must contain at least one Condition resource")

    for problem in problems:
        codes = problem.get('code', {}).get('coding', [])
        namaste_codes = [c for c in codes if c.get('system') == "http://example.org/fhir/CodeSystem/namaste"]
        
        # Validate NAMASTE codes
        for nc in namaste_codes:
            code = nc['code']
            cursor = conn.cursor()
            cursor.execute("SELECT \"TM2 Code\" FROM mapped_terms WHERE NAMC_CODE = ?", (code,))
            result = cursor.fetchone()
            if not result:
                raise HTTPException(400, f"No TM2 mapping for NAMASTE code {code}")
            tm2_code = result[0]
            
            # Verify TM2 code in coding list; add if missing
            existing_tm2 = any(c.get('system') == "http://who.int/icd11/tm2" and c.get('code') == tm2_code for c in codes)
            if not existing_tm2:
                try:
                    lookup_response = biomed_lookup(code=tm2_code)
                    codes.append({
                        "system": "http://who.int/icd11/tm2",
                        "code": tm2_code,
                        "display": lookup_response.get('display', '')
                    })
                except HTTPException:
                    codes.append({
                        "system": "http://who.int/icd11/tm2",
                        "code": tm2_code,
                        "display": ""
                    })
                    logger.warning(f"Could not fetch TM2 display for {tm2_code}")

        # Validate extensions
        extensions = problem.get('extension', [])
        expected_extensions = [
            "http://example.org/fhir/extension/index-term",
            "http://example.org/fhir/extension/short-definition",
            "http://example.org/fhir/extension/long-definition",
            "http://example.org/fhir/extension/tm2-definition"
        ]
        existing_urls = [ext.get('url') for ext in extensions]
        
        # Enrich missing extensions if necessary
        for nc in namaste_codes:
            code = nc['code']
            if "http://example.org/fhir/extension/short-definition" not in existing_urls or \
               "http://example.org/fhir/extension/long-definition" not in existing_urls or \
               "http://example.org/fhir/extension/index-term" not in existing_urls:
                try:
                    with open('namaste_codesystem.json', 'r', encoding='utf-8') as f:
                        cs = json.load(f)
                    concepts = cs.get("concept", [])
                    concept = next((c for c in concepts if c.get("code") == code), None)
                    if concept:
                        if "http://example.org/fhir/extension/short-definition" not in existing_urls:
                            extensions.append({
                                "url": "http://example.org/fhir/extension/short-definition",
                                "valueString": concept.get("display", nc.get("display", ""))
                            })
                        if "http://example.org/fhir/extension/long-definition" not in existing_urls:
                            extensions.append({
                                "url": "http://example.org/fhir/extension/long-definition",
                                "valueString": concept.get("definition", "")
                            })
                        if "http://example.org/fhir/extension/index-term" not in existing_urls:
                            extensions.append({
                                "url": "http://example.org/fhir/extension/index-term",
                                "valueString": concept.get("display", nc.get("display", ""))
                            })
                except Exception as e:
                    logger.warning(f"Could not fetch NAMASTE details for {code}: {str(e)}")

        # Enrich TM2 definition if missing
        for c in codes:
            if c.get('system') == "http://who.int/icd11/tm2" and \
               "http://example.org/fhir/extension/tm2-definition" not in existing_urls:
                try:
                    lookup_response = biomed_lookup(code=c['code'])
                    extensions.append({
                        "url": "http://example.org/fhir/extension/tm2-definition",
                        "valueString": lookup_response.get('definition', '')
                    })
                except HTTPException:
                    pass  # Skip if lookup fails

        problem['extension'] = extensions

    # Add meta to bundle
    bundle['meta'] = {
        "versionId": "1",
        "lastUpdated": datetime.now().isoformat(),
        "tag": [{"code": "consent-granted"}]
    }

    # Send to Supabase
    try:
        supabase_url =  os.getenv("SUPABASE_URL") 
        supabase_key = os.getenv("SUPABASE_KEY")
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        supabase_data = {
            "bundle_data": bundle  # Assumes a jsonb column 'bundle_data' in table 'fhir_bundles'
        }
        response = requests.post(f"{supabase_url}/rest/v1/fhir_bundles", headers=headers, json=supabase_data)
        response.raise_for_status()
        logger.info(f"Bundle successfully uploaded to Supabase")
    except Exception as e:
        raise HTTPException(500, f"Failed to upload to Supabase: {str(e)}")

    return bundle

# Entry point
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
