import requests, json, time
base = 'http://127.0.0.1:8002'
# Register user
resp = requests.post(f'{base}/auth/register', json={'email':'test@example.com','password':'test123'})
print('Register:', resp.status_code, resp.text)
# Login to get token
resp = requests.post(f'{base}/auth/token', data={'username':'test@example.com','password':'test123'})
print('Login:', resp.status_code, resp.text)
token = resp.json().get('access_token')
headers = {'Authorization': f'Bearer {token}'}
# Create a project
resp = requests.post(f'{base}/projects', json={'name':'Demo Project'}, headers=headers)
print('Create project:', resp.status_code, resp.text)
project_id = resp.json()['id']
# Upload test document
files = {'file': ('test.txt', open('c:/Users/aymoh/.gemini/antigravity-ide/brain/5f477dcb-e127-40d5-b98e-02fbafbb5b85/scratch/test.txt', 'rb'))}
resp = requests.post(f'{base}/projects/{project_id}/documents', files=files, headers=headers)
print('Upload doc:', resp.status_code, resp.text)
# Wait a moment for processing
time.sleep(1)
# Perform QA
qa_resp = requests.post(f'{base}/projects/{project_id}/qa', json={'question':'What number appears in the document?'}, headers=headers)
print('QA:', qa_resp.status_code, qa_resp.text)
