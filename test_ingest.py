import requests
import json
import os
from pathlib import Path

BASE_URL = 'http://127.0.0.1:8000'

def register(email, password):
    resp = requests.post(f'{BASE_URL}/auth/register', json={'email': email, 'password': password})
    resp.raise_for_status()
    return resp.json()['access_token']

def login(email, password):
    resp = requests.post(f'{BASE_URL}/auth/token', data={'username': email, 'password': password})
    resp.raise_for_status()
    return resp.json()['access_token']

def create_project(token, name):
    resp = requests.post(f'{BASE_URL}/projects', json={'name': name}, headers={'Authorization': f'Bearer {token}'})
    resp.raise_for_status()
    return resp.json()['id']

def upload_document(token, project_id, file_path):
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f)}
        resp = requests.post(f'{BASE_URL}/projects/{project_id}/documents', files=files, headers={'Authorization': f'Bearer {token}'})
    resp.raise_for_status()
    return resp.json()

def main():
    email = 'test@example.com'
    password = 'password123'
    token = register(email, password)
    print('Registered, token:', token)
    # login optional
    # token = login(email, password)
    project_id = create_project(token, 'Demo Project')
    print('Created project', project_id)
    test_dir = Path('test_files')
    results = []
    for file_path in test_dir.iterdir():
        if file_path.is_file():
            res = upload_document(token, project_id, str(file_path))
            results.append(res)
            print('Uploaded', file_path.name, '=>', res['status'])
    print('All uploads done')
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
