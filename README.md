# Executable proof of concept: BPMN calling a REST API

The case-study process is not only drawn, it also runs. In this proof of concept, a Camunda 8 process executes as real REST calls against a mock service built from the OpenAPI spec, and the data changes in a database. It covers a happy path and a business-rule failure path.

All names and data are illustrative; no real company data is used.

## What is here

| Item | Purpose |
|---|---|
| `Fix_Internet_problems__REST_API_Error_processing__.bpmn` | Executable Camunda 8 model: four REST service tasks, an error boundary event and a manual user task |
| [`mock-api/`](mock-api/) | FastAPI + SQLite service implementing `POST`, `GET` and `PATCH /activities` from the OpenAPI spec |
| [`screenshots/`](screenshots/) | Evidence of both runs |

## How it works

![Executable BPMN](https://github.com/oleksiymilner/Executable-POC-BPMN-calling-REST-API/blob/main/Fix%20Internet%20problems%20with%20REST%20API%20calls.png)

| Task | REST call | Effect |
|---|---|---|
| Create Activity in the Bucket | `POST /activities` with `activityType`, `date`, `resourceId` | A new activity is inserted with status `pending` in the bucket. The `activityId` from the response is stored as a process variable. |
| Reassign Activity To Technician | `PATCH /activities/{activityId}` with `resourceId` taken from the variable `technicianId` | The activity is reassigned. If the service returns `422` (technician lacks the required work skill), an error expression raises a BPMN error and the **Skills Mismatch** boundary event routes the process to the manual task. |
| Start Activity | `PATCH /activities/{activityId}` | The status is updated to `started`. |
| Complete Activity | `PATCH /activities/{activityId}` with `status: completed` | The status is updated to `completed`. |
| Clarify and manually Assign to Technician | none (user task in Tasklist) | A dispatcher handles the mismatch manually. |

**Process inputs.** The instance is started with two variables:

```json
{"baseUrl": "https://your-tunnel.trycloudflare.com", "technicianId": 31}
```

- `baseUrl` is the address of the mock service, so the URL is not stored in the model. Use no trailing slash.
- `technicianId` selects the path: `31` (Technician A, has the required skill) gives the happy path; `32` (Technician B, lacks it) gives the failure path.

## Evidence

### Happy path (`technicianId` 31)

The instance completes. The service log shows one `POST` and three `PATCH` calls on the same activity.

![Happy path in Operate](https://github.com/oleksiymilner/Executable-POC-BPMN-calling-REST-API/blob/main/screenshots/Happy%20path%20operate.png)

![Happy path service log](https://github.com/oleksiymilner/Executable-POC-BPMN-calling-REST-API/blob/main/screenshots/happy%20path%20service.png)

### Failure path (`technicianId` 32)

The reassignment returns `422`, the Skills Mismatch boundary event fires, and the process waits at the manual task with no incident. The two `PATCH` 200 calls that follow in the log come from Start Activity and Complete Activity, after the manual task was completed.

![Failure path in Operate](https://github.com/oleksiymilner/Executable-POC-BPMN-calling-REST-API/blob/main/screenshots/Skills%20mismatch%20Operate.png)

![Failure path service log](https://github.com/oleksiymilner/Executable-POC-BPMN-calling-REST-API/blob/main/screenshots/Skills%20Mismath%20service.png)

### Database after both runs

![Database rows](https://github.com/oleksiymilner/Executable-POC-BPMN-calling-REST-API/blob/main/screenshots/DB%20updates.png)

- Activity 6 (happy path): `completed`, assigned to technician 31.
- Activity 7 (failure path): `completed`, still assigned to resource 25 (the bucket). See the known simplification below.

## Run it yourself

1. **Start the mock service.** Follow [`mock-api/README.md`](mock-api/README.md) (Python 3.12 or 3.13). Set the token the process will send before starting: `$env:DEMO_TOKEN="your-token"` in PowerShell.
2. **Make the service reachable.** Camunda SaaS cannot call localhost, so expose the service with a temporary tunnel, for example `cloudflared tunnel --url http://localhost:8000`. Alternatively, run Camunda 8 locally and use localhost directly.
3. **Set the token in the model.** The exported model contains the placeholder `{{BEARER_TOKEN}}`. In your own cluster, create a connector secret and reference it as `{{secrets.<NAME>}}` in the authentication field of each task. The secret value must equal the service token.
4. **Start an instance.** In Web Modeler, open the **Implement** tab, click **Run**, and enter the variables JSON shown above.
5. **Check the result** in Operate and in the database:
   ```
   python -c "import sqlite3; [print(r) for r in sqlite3.connect('outage.db').execute('select * from activity')]"
   ```

## Limitations and next steps

- The bearer-token check is a static token, not real JWT validation. The tunnel is temporary and the database is a single SQLite file; this is a demo setup, not a deployment.
- **Known simplification:** the manual task does not assign a technician, so after it the process still starts and completes the activity while it remains in the bucket (see activity 7 above). A fuller design would loop back to the reassignment task with a technician chosen by the dispatcher.
- The Skills Mismatch boundary event has no error code attached, so it catches any BPMN error raised by that task. The error expression raises one only for `422`.
- The executable model covers a reduced flow. SLA check, the 30-minute escalation timer, follow-up visit and customer confirmation stay in the full diagram in the main case-study repository.
- Planned: decision tables for the SLA check and technician matching.

## Tools

Camunda 8 SaaS (Web Modeler, Operate, Tasklist, REST Outbound Connector), FastAPI, SQLite, Cloudflare quick tunnel.



