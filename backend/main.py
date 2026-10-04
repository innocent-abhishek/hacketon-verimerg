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

# Database (SQLite for demo)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./verimerge.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class ProjectCreate(BaseModel):
    name: str

class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: str
    created_at: datetime

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

@app.post("/auth/register", response_model=Token)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
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

@app.post("/projects")
def create_project(proj: ProjectCreate, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_proj = Project(name=proj.name, owner_id=current.id)
    db.add(db_proj)
    db.commit()
    db.refresh(db_proj)
    return {"id": db_proj.id, "name": db_proj.name}

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
    extracted = None
    if file.filename.lower().endswith('.txt'):
        extracted = content.decode(errors='ignore')
    doc = Document(project_id=project_id, filename=file.filename, sha256=sha,
                  status='READY' if extracted else 'FAILED',
                  content={'text': extracted} if extracted else None)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return DocumentResponse(id=doc.id, filename=doc.filename, status=doc.status, created_at=doc.created_at)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
