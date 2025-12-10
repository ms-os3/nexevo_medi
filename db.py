import os
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def upsert_abha_link(record: dict):
    return supabase.table("abha_links").upsert(record, on_conflict=["emr_patient_id"]).execute()

def get_abha_link(emr_patient_id: str):
    response = supabase.table("abha_links").select("*").eq("emr_patient_id", emr_patient_id).execute()
    return response.data[0] if response.data else None

def update_abha_link(emr_patient_id: str, updates: dict):
    return supabase.table("abha_links").update(updates).eq("emr_patient_id", emr_patient_id).execute()


def log_event(event_type: str, emr_patient_id: str, emr_client_id: str = None, metadata: dict = {}):
    log_data = {
        "event_type": event_type,
        "emr_patient_id": emr_patient_id,
        "metadata": metadata,
        "timestamp": datetime.utcnow().isoformat()
    }
    if emr_client_id is not None:
        log_data["emr_client_id"] = emr_client_id

    return supabase.table("audit_logs").insert(log_data).execute()

