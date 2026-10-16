# Mock API for the Customer Outage Request case study

A small REST service (FastAPI + SQLite) that implements the `POST /activities`, `GET /activities/{activityId}` and `PATCH /activities/{activityId}` contract from the OpenAPI spec. It writes to a real local database, so a BPMN service task can make an actual REST call that changes data.

Illustrative only. The bearer-token check uses a static token, not real JWT validation.

## Run it

```
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
uvicorn app:app --port 8000
```

The SQLite file `outage.db` is created on first start with seed data. Delete it to reset.

## Try it

- **Swagger UI:** open http://127.0.0.1:8000/docs, click **Authorize**, enter `demo-token`, then use **Try it out**.
- **Smoke test:** with the service running, `python smoke_test.py` runs 13 scenarios covering every status code.
- **Postman:** import http://127.0.0.1:8000/openapi.json and set Bearer token `demo-token`.

## Seed data

| resourceId | Name | Type | Work skills |
|---|---|---|---|
| 25 | Service bucket | bucket | n/a (accepts any activity) |
| 31 | Technician A | technician | INTERNET_REPAIR |
| 32 | Technician B | technician | CABLE_INSTALL |

Activity types map to the skill they require: `repair` → INTERNET_REPAIR, `installation` → CABLE_INSTALL. The skill is derived by the service, which is why `workSkill` is `readOnly` in the spec.

## Behavior

| Request | Result |
|---|---|
| any request without `Authorization: Bearer demo-token` | `401` |
| `POST /activities` valid, resource exists | `201`, status `pending`, row inserted |
| `POST` invalid body or unknown `activityType` | `400` |
| `POST` / `PATCH` unknown resource | `404` |
| `POST` / `PATCH` technician without the required skill | `422` |
| `GET` / `PATCH` unknown activity | `404` |
| `PATCH` with `resourceId` and/or `status` | `200`, row updated |
| `PATCH` with empty body | `400` |

Errors always return `{"message": "..."}`.

**Spec note:** `POST` can also return `422` (creating work directly on a technician without the skill). Add a `422` response to `POST /activities` in your OpenAPI file so the contract matches the service.

## Inspect the database

```
python -c "import sqlite3; [print(r) for r in sqlite3.connect('outage.db').execute('select * from activity')]"
```

Or open `outage.db` in [DB Browser for SQLite](https://sqlitebrowser.org/).

## Connect it to the BPMN service task

In Camunda Modeler, change **Create activity in the bucket** to a **service task** and apply the **REST Outbound Connector** template (Camunda 8). Typical settings (field labels vary slightly by version):

- **Method / URL:** `POST` `http://localhost:8000/activities`
- **Authentication:** Bearer, token `demo-token`
- **Payload (FEEL):** `={activityType: "repair", date: string(today()), resourceId: 25}`
- **Result expression:** `={activityId: response.body.activityId}`

The result expression stores the new `activityId` as a process variable, so a later **Reassign activity to Technician** task can call `PATCH /activities/{activityId}`.

**Reachability:** the connector runs where your Camunda engine runs. A local Camunda 8 Run can call `localhost:8000` directly. Camunda SaaS cannot reach your laptop, so you would need a tunnel (ngrok or cloudflared) or a public deployment of this service.

**Executable model:** Camunda executes one pool as the process. Keep a separate runnable copy of the diagram containing only the service provider pool, and leave the portfolio diagram as the readable version.
