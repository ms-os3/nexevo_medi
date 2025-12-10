import requests

token_endpoint = 'https://icdaccessmanagement.who.int/connect/token'
client_id = 'ec25aa27-20e5-45be-ae55-09fe40516d90_1dccbaa7-142e-484e-9bb9-ccfec84ee1c6'
client_secret = 'C4Ychrqu0/24KxTEINa20LG3zhUBN8lqshviMSbSFxI='
scope = 'icdapi_access'
grant_type = 'client_credentials'


# get the OAUTH2 token

# set data to post
payload = {'client_id': client_id, 
	   	   'client_secret': client_secret, 
           'scope': scope, 
           'grant_type': grant_type}
           
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