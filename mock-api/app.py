"""Mock REST API for the Customer Outage Request case study.

Implements the contract from the OpenAPI spec (POST/GET/PATCH /activities) on top of
a local SQLite database, so a BPMN service task can make a real REST call that
changes real data. Illustrative only: the bearer-token check is a simple static token,
not real JWT validation.
"""
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import date as date_type
from enum import Enum
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

DB_PATH = os.getenv("DB_PATH", "outage.db")
DEMO_TOKEN = os.getenv("DEMO_TOKEN", "demo-token")

# Business rule: which work skill an activity type requires.
ACTIVITY_TYPE_SKILL = {
    "repair": "INTERNET_REPAIR",
    "installation": "CABLE_INSTALL",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS resource (
    resource_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('bucket', 'technician'))
);
CREATE TABLE IF NOT EXISTS resource_work_skill (
    resource_id INTEGER NOT NULL REFERENCES resource(resource_id),
    work_skill  TEXT NOT NULL,
    PRIMARY KEY (resource_id, work_skill)
);
CREATE TABLE IF NOT EXISTS activity (
    activity_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_type TEXT NOT NULL,
    date          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    resource_id   INTEGER NOT NULL REFERENCES resource(resource_id),
    work_skill    TEXT NOT NULL
);
"""

SEED_RESOURCES = [
    (25, "Service bucket", "bucket"),
    (31, "Technician A", "technician"),
    (32, "Technician B", "technician"),
]
SEED_SKILLS = [
    (31, "INTERNET_REPAIR"),
    (32, "CABLE_INSTALL"),
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT OR IGNORE INTO resource VALUES (?, ?, ?)", SEED_RESOURCES)
        conn.executemany("INSERT OR IGNORE INTO resource_work_skill VALUES (?, ?)", SEED_SKILLS)
        conn.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="DEMO (example)", version="1.0.0", lifespan=lifespan)


# ---------- models ----------
class Status(str, Enum):
    pending = "pending"
    started = "started"
    completed = "completed"


class ActivityCreate(BaseModel):
    activityType: str
    date: date_type
    resourceId: int


class ActivityUpdate(BaseModel):
    resourceId: Optional[int] = None
    status: Optional[Status] = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.resourceId is None and self.status is None:
            raise ValueError("Provide at least one of: resourceId, status")
        return self


class Activity(BaseModel):
    activityId: int
    activityType: str
    date: date_type
    resourceId: int
    status: Status
    workSkill: str


# ---------- errors: always {"message": ...}, 400 for invalid input ----------
@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    parts = []
    for e in exc.errors():
        field = ".".join(str(p) for p in e["loc"] if p != "body")
        msg = e["msg"].removeprefix("Value error, ")
        parts.append(f"{field}: {msg}" if field else msg)
    details = "; ".join(parts)
    return JSONResponse(status_code=400, content={"message": f"Invalid request: {details}"})


# ---------- security ----------
# Declared as an HTTP bearer scheme so Swagger UI shows an Authorize button
# and /openapi.json contains the same bearerAuth scheme as the spec.
bearer_scheme = HTTPBearer(auto_error=False)


def require_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> None:
    if credentials is None or credentials.credentials != DEMO_TOKEN:
        raise HTTPException(401, "Missing or invalid token")


# ---------- helpers ----------
def to_activity(row: sqlite3.Row) -> dict:
    return {
        "activityId": row["activity_id"],
        "activityType": row["activity_type"],
        "date": row["date"],
        "resourceId": row["resource_id"],
        "status": row["status"],
        "workSkill": row["work_skill"],
    }


def get_resource(conn: sqlite3.Connection, resource_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM resource WHERE resource_id = ?", (resource_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Resource not found")
    return row


def check_skill(conn: sqlite3.Connection, resource: sqlite3.Row, work_skill: str) -> None:
    """Technicians must hold the required skill; buckets accept any activity."""
    if resource["type"] != "technician":
        return
    has_skill = conn.execute(
        "SELECT 1 FROM resource_work_skill WHERE resource_id = ? AND work_skill = ?",
        (resource["resource_id"], work_skill),
    ).fetchone()
    if not has_skill:
        raise HTTPException(422, "Resource does not have the required work skill")


# ---------- endpoints ----------
@app.post("/activities", response_model=Activity, status_code=201, dependencies=[Depends(require_token)])
def create_activity(body: ActivityCreate):
    work_skill = ACTIVITY_TYPE_SKILL.get(body.activityType)
    if work_skill is None:
        raise HTTPException(400, f"Unknown activityType. Allowed: {', '.join(ACTIVITY_TYPE_SKILL)}")
    with closing(connect()) as conn:
        resource = get_resource(conn, body.resourceId)
        check_skill(conn, resource, work_skill)
        cur = conn.execute(
            "INSERT INTO activity (activity_type, date, status, resource_id, work_skill) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (body.activityType, body.date.isoformat(), body.resourceId, work_skill),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM activity WHERE activity_id = ?", (cur.lastrowid,)).fetchone()
        return to_activity(row)


@app.get("/activities/{activityId}", response_model=Activity, dependencies=[Depends(require_token)])
def read_activity(activityId: int):
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM activity WHERE activity_id = ?", (activityId,)).fetchone()
        if row is None:
            raise HTTPException(404, "Activity not found")
        return to_activity(row)


@app.patch("/activities/{activityId}", response_model=Activity, dependencies=[Depends(require_token)])
def update_activity(activityId: int, body: ActivityUpdate):
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM activity WHERE activity_id = ?", (activityId,)).fetchone()
        if row is None:
            raise HTTPException(404, "Activity not found")
        if body.resourceId is not None:
            resource = get_resource(conn, body.resourceId)
            check_skill(conn, resource, row["work_skill"])
            conn.execute("UPDATE activity SET resource_id = ? WHERE activity_id = ?", (body.resourceId, activityId))
        if body.status is not None:
            conn.execute("UPDATE activity SET status = ? WHERE activity_id = ?", (body.status.value, activityId))
        conn.commit()
        row = conn.execute("SELECT * FROM activity WHERE activity_id = ?", (activityId,)).fetchone()
        return to_activity(row)
