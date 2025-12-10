import uuid
import secrets
from supabase import create_client, Client
import os
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def create_emr_client(client_name: str):
    client_id = str(uuid.uuid4())
    client_secret = secrets.token_urlsafe(32)

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": client_name
    }
    response = supabase.table("emr_clients").insert(data).execute()

    if response.data:
        # Insert was successful, response.data contains inserted rows
        return {
            "client_id": client_id,
            "client_secret": client_secret
        }
    else:
        print("Insert failed:", response)
        raise Exception("Error creating client")

new_client = create_emr_client("Somaiya_hospital_EMR")
print("New EMR client created:", new_client)