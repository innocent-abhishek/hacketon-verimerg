import requests, json, os
from pathlib import Path

BASE_URL = 'http://127.0.0.1:8000'

def register(email, password):
    r = requests.post(f'{BASE_URL}/auth/register', json={'email': email, 'password': password})
    r.raise_for_status()
    return r.json()['access_token']

def create_project(token, name):
    r = requests.post(f'{BASE_URL}/projects', json={'name': name}, headers={'Authorization': f'Bearer {token}'})
    r.raise_for_status()
    return r.json()['id']

def upload_document(token, project_id, file_path):
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f)}
        r = requests.post(f'{BASE_URL}/projects/{project_id}/documents', files=files, headers={'Authorization': f'Bearer {token}'})
    r.raise_for_status()
    return r.json()

def ask_question(token, project_id, question):
    r = requests.post(f'{BASE_URL}/projects/{project_id}/qa', json={'question': question}, headers={'Authorization': f'Bearer {token}'})
    r.raise_for_status()
    return r.json()

def fetch_citation(token, doc_id, chunk_index):
    # No endpoint, so we directly read DB file
    import sqlite3, json
    conn = sqlite3.connect('verimerge.db')
    cur = conn.cursor()
    cur.execute('SELECT content FROM documents WHERE id = ?', (doc_id,))
    row = cur.fetchone()
    if not row:
        return None
    content = json.loads(row[0])
    chunks = content.get('chunks', [])
    if 0 <= chunk_index < len(chunks):
        return chunks[chunk_index]
    return None

def main():
    email = 'test2@example.com'
    password = 'password123'
    token = register(email, password)
    print('Token:', token)
    project_id = create_project(token, 'Demo')
    print('Project ID:', project_id)
    test_dir = Path('test_files')
    for f in test_dir.iterdir():
        if f.is_file():
            res = upload_document(token, project_id, str(f))
            print('Uploaded', f.name, 'status', res['status'])
    # Ask a question expected to have evidence
    q1 = 'Hello world'
    ans1 = ask_question(token, project_id, q1)
    print('Answer 1:', ans1['answer'])
    print('Citations:', ans1['citations'])
    for cit in ans1['citations']:
        snippet = fetch_citation(token, cit['document_id'], cit['chunk_index'])
        print('Citation source snippet:', snippet[:100])
    # Question with insufficient evidence
    q2 = 'nonexistent phrase xyz'
    ans2 = ask_question(token, project_id, q2)
    print('Answer 2:', ans2['answer'])
    print('Citations 2:', ans2['citations'])
    # Contradictory evidence: ask numeric claim that may differ across files
    q3 = '10'
    ans3 = ask_question(token, project_id, q3)
    print('Answer 3:', ans3['answer'])
    print('Citations 3:', ans3['citations'])

if __name__ == '__main__':
    main()
