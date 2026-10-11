# backend/main.py
import os
import hashlib
import uuid
from typing import Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import uvicorn
# Additional libraries for document ingestion
import fitz  # PyMuPDF
import docx
import pandas as pd
import re
from io import BytesIO

# Database (SQLite for demo)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./verimerge.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
# Base.metadata.create_all(bind=engine)  # deferred until after models are defined

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    owner_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    sha256 = Column(String, nullable=False)
    status = Column(String, default="UPLOADING")
    created_at = Column(DateTime, default=datetime.utcnow)
    content = Column(JSON, nullable=True)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=False)
    project_id = Column(String, nullable=False)
    index = Column(String, nullable=False)  # chunk index within document
    text = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# create tables after all models are defined
Base.metadata.create_all(bind=engine)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class ProjectCreate(BaseModel):
    name: str

class ProjectResponse(BaseModel):
    id: str
    name: str
    created_at: datetime

class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: str
    created_at: datetime
    sha256: str
    content: Optional[dict] = None

# Auth utils (simple JWT for demo)
from jose import JWTError, jwt
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

def get_password_hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def verify_password(pw: str, hashed: str) -> bool:
    return hashlib.sha256(pw.encode()).hexdigest() == hashed

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

auth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(auth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

app = FastAPI(title="VeriMerge Backend")

# Allow CORS for frontend development
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/auth/register", response_model=Token)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        # Return token for existing user instead of error
        return Token(access_token=create_access_token({"sub": existing_user.id}))
    db_user = User(email=user.email, hashed_password=get_password_hash(user.password))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return Token(access_token=create_access_token({"sub": db_user.id}))

@app.post("/auth/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    return Token(access_token=create_access_token({"sub": user.id}))

@app.get("/projects")
def list_projects(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List projects owned by the authenticated user."""
    projects = db.query(Project).filter(Project.owner_id == current.id).all()
    return [{"id": p.id, "name": p.name, "created_at": p.created_at} for p in projects]

@app.post("/projects", response_model=ProjectResponse)
def create_project(proj: ProjectCreate, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_proj = Project(name=proj.name, owner_id=current.id)
    db.add(db_proj)
    db.commit()
    db.refresh(db_proj)
    return {"id": db_proj.id, "name": db_proj.name, "created_at": db_proj.created_at}



UPLOAD_DIR = os.path.abspath("./uploaded_files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

def compute_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(4096), b""):
            h.update(b)
    return h.hexdigest()

@app.post("/projects/{project_id}/documents", response_model=DocumentResponse)
async def upload_document(project_id: str, file: UploadFile = File(...), current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id, Project.owner_id == current.id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    sha = compute_sha256(file_path)

    # Extraction based on file type
    extracted_text = None
    try:
        lower = file.filename.lower()
        if lower.endswith('.txt'):
            extracted_text = content.decode(errors='ignore')
        elif lower.endswith('.pdf'):
            doc_pdf = fitz.open(file_path)
            texts = [page.get_text() for page in doc_pdf]
            extracted_text = "\n".join(texts)
        elif lower.endswith('.docx'):
            doc_docx = docx.Document(BytesIO(content))
            extracted_text = "\n".join([p.text for p in doc_docx.paragraphs])
        elif lower.endswith('.csv'):
            df = pd.read_csv(BytesIO(content))
            extracted_text = df.to_csv(index=False)
        elif lower.endswith('.xlsx') or lower.endswith('.xls'):
            df = pd.read_excel(BytesIO(content))
            extracted_text = df.to_csv(index=False)
        else:
            raise ValueError("Unsupported file type")
    except Exception as e:
        doc = Document(project_id=project_id, filename=file.filename, sha256=sha,
                      status="FAILED", content={"error": str(e)})
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return DocumentResponse(id=doc.id, filename=doc.filename, status=doc.status,
                                created_at=doc.created_at, sha256=doc.sha256, content=doc.content)

    # Chunk the text (simple fixed size)
    def chunk_text(text: str, size: int = 1000) -> list:
        return [text[i:i+size] for i in range(0, len(text), size)]

    chunks = chunk_text(extracted_text)
    metadata = {
        "filename": file.filename,
        "size_bytes": len(content),
        "extracted_bytes": len(extracted_text.encode()),
        "file_type": lower.split('.')[-1]
    }
    doc = Document(project_id=project_id, filename=file.filename, sha256=sha,
                  status="READY", content={"metadata": metadata, "text": extracted_text})
    db.add(doc)
    db.commit()
    db.refresh(doc)
    # Store chunks separately
    for idx, chunk_text in enumerate(chunks):
        chunk = Chunk(document_id=doc.id, project_id=project_id, index=str(idx), text=chunk_text)
        db.add(chunk)
    db.commit()
    # Return document response with minimal info
    return DocumentResponse(id=doc.id, filename=doc.filename, status=doc.status,
                            created_at=doc.created_at, sha256=doc.sha256, content=doc.content)



@app.get("/projects/{project_id}/search")
def keyword_search(project_id: str, q: str, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Keyword search over stored chunks. Returns matching chunks with snippet and metadata."""
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' required")
    chunks = db.query(Chunk).filter(Chunk.project_id == project_id).all()
    results = []
    for chunk in chunks:
        if q.lower() in chunk.text.lower():
            # retrieve document info
            doc = db.query(Document).filter(Document.id == chunk.document_id).first()
            results.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "filename": doc.filename if doc else None,
                "snippet": chunk.text[:200],
                "index": chunk.index,
            })
    return {"query": q, "results": results}

@app.post("/projects/{project_id}/qa")
def answer_question(project_id: str, query: dict, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """QA endpoint that searches for relevant chunks and extracts numeric values. If no direct matches, returns numbers found in the project."""
    q = query.get("question", "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question is required")
    # Search for matching chunks
    chunks = db.query(Chunk).filter(Chunk.project_id == project_id).all()
    matches = []
    for chunk in chunks:
        if q.lower() in chunk.text.lower():
            matches.append({
                "document_id": chunk.document_id,
                "chunk_id": chunk.id,
                "snippet": chunk.text[:200],
                "index": chunk.index,
            })
    # If no direct matches, fall back to extracting numbers from all chunks
    if not matches:
        # Find all numeric values in the project's text chunks
        all_text = " ".join([c.text for c in chunks])
        numbers = list(set(re.findall(r"\\b\\d+\\b", all_text)))
        if numbers:
            answer = f"Numbers found: {', '.join(numbers)}"
            return {"answer": answer, "citations": [], "numbers": numbers}
        else:
            return {"answer": "Insufficient evidence to answer the question.", "citations": [], "numbers": []}
    # Concatenate snippets for answer
    answer = " ".join([m["snippet"] for m in matches[:3]])
    numbers = list(set(re.findall(r"\\b\\d+\\b", answer)))
    return {"answer": answer, "citations": matches, "numbers": numbers}


# Orchestrator and simple agent implementations
from fastapi import BackgroundTasks
import logging

logger = logging.getLogger("verimerge.orchestrator")
logging.basicConfig(level=logging.INFO)

# Simple agent functions
def summarize_all_documents(project_id: str, db: Session):
    docs = db.query(Document).filter(Document.project_id == project_id, Document.status == "READY").all()
    summaries = []
    for doc in docs:
        text = doc.content.get("text", "")
        summary = text[:200]
        summaries.append({"document_id": doc.id, "summary": summary})
        logger.info(f"SummarizeAgent: summarized document {doc.id}")
    return summaries

def compare_documents(project_id: str, doc_id1: str, doc_id2: str, db: Session):
    d1 = db.query(Document).filter(Document.id == doc_id1, Document.project_id == project_id).first()
    d2 = db.query(Document).filter(Document.id == doc_id2, Document.project_id == project_id).first()
    if not d1 or not d2:
        raise HTTPException(status_code=404, detail="Document not found")
    txt1 = d1.content.get("text", "")
    txt2 = d2.content.get("text", "")
    common = set(txt1.split()) & set(txt2.split())
    logger.info(f"CompareAgent: compared {doc_id1} vs {doc_id2}")
    return {"common_words": list(common)[:20]}

def find_contradictions(project_id: str, db: Session):
    docs = db.query(Document).filter(Document.project_id == project_id, Document.status == "READY").all()
    contradictions = []
    import re
    values = {}
    for doc in docs:
        text = doc.content.get("text", "")
        nums = re.findall(r"\b\d+\b", text)
        for n in nums:
            values.setdefault(n, []).append(doc.id)
    for num, ids in values.items():
        if len(ids) > 1:
            contradictions.append({"value": num, "documents": ids})
    logger.info("ConflictAgent: found contradictions")
    return contradictions

def verify_claim(project_id: str, claim: str, db: Session):
    docs = db.query(Document).filter(Document.project_id == project_id, Document.status == "READY").all()
    evidence = []
    for doc in docs:
        text = doc.content.get("text", "")
        if claim.lower() in text.lower():
            evidence.append({"document_id": doc.id, "snippet": text[:200]})
    result = {"claim": claim, "supported": bool(evidence), "evidence": evidence}
    logger.info("VerificationAgent: verified claim")
    return result

def generate_report(project_id: str, db: Session):
    summary = summarize_all_documents(project_id, db)
    contradictions = find_contradictions(project_id, db)
    report = {"project_id": project_id, "summaries": summary, "contradictions": contradictions}
    logger.info("ReportAgent: generated report")
    return report

@app.post("/orchestrator/{project_id}/{task}")
def orchestrate(project_id: str, task: str, payload: dict = None, background: BackgroundTasks = None, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Orchestrator endpoint that routes tasks to simple agent functions.
    task can be: summarize, compare, contradictions, verify, report.
    payload varies per task.
    """
    if task == "summarize":
        return {"summaries": summarize_all_documents(project_id, db)}
    elif task == "compare":
        doc1 = payload.get("doc1")
        doc2 = payload.get("doc2")
        return compare_documents(project_id, doc1, doc2, db)
    elif task == "contradictions":
        return {"contradictions": find_contradictions(project_id, db)}
    elif task == "verify":
        claim = payload.get("claim", "")
        return verify_claim(project_id, claim, db)
    elif task == "report":
        return generate_report(project_id, db)
    else:
        raise HTTPException(status_code=400, detail="Unknown task")
@app.get("/ping")
def ping():
    return {"ping": "pong"}
