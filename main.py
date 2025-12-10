import os
import requests
from dotenv import load_dotenv

load_dotenv()

token_endpoint = 'https://icdaccessmanagement.who.int/connect/token'
# read credentials from environment (or .env)
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
scope = 'icdapi_access'
grant_type = 'client_credentials'

# fail fast if credentials are missing
if not client_id or not client_secret:
    raise RuntimeError('CLIENT_ID and CLIENT_SECRET must be set in environment or in a .env file')


# get the OAUTH2 token

# set data to post
payload = {
    'client_id': client_id,
    'client_secret': client_secret,
    'scope': scope,
    'grant_type': grant_type,
}
           
# make request
r = requests.post(token_endpoint, data=payload, verify=False).json()
token = r['access_token']


# access ICD API

uri = 'https://id.who.int/icd/entity'

# HTTP header fields to set
headers = {'Authorization':  'Bearer '+token, 
           'Accept': 'application/json', 
           'Accept-Language': 'en',
	   'API-Version': 'v2'}
           
# make request           
r = requests.get(uri, headers=headers, verify=False)

# print the result
print (r.text)			