import requests, json
BASE_URL='http://127.0.0.1:8000'
payload={'email':'test2@example.com','password':'password123'}
resp=requests.post(f'{BASE_URL}/auth/register', json=payload)
print('Status:', resp.status_code)
print('Response:', resp.text)
