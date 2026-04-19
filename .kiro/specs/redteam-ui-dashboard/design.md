# Design Document: RedTeam UI Dashboard

## Overview

The RedTeam UI Dashboard is a minimal, browser-based operator interface for the AutoRedTeam pipeline. It consists of three artifacts:

1. **`trigger_lambda.py`** — single-file Python Lambda that starts a `RedTeamMainOrchestrator` Step Functions execution
2. **`status_lambda.py`** — single-file Python Lambda that polls execution status and fetches the S3 run summary
3. **`index.html`** — single-page dashboard with inline CSS/JS, hosted on S3

All backend communication goes through an API Gateway HTTP API. The frontend requires no build toolchain and has no external JS dependencies.

### Design Goals

- **Zero-dependency frontend**: One HTML file, no npm, no bundler, no CDN scripts
- **Minimal Lambda surface**: Each Lambda is a single `.py` file using only `boto3` (built into Lambda runtime)
- **Console-deployable**: No CLI required; all steps executable via AWS Management Console
- **CORS-safe**: All Lambda responses include `Access-Control-Allow-Origin: *`

---

## Architecture

```mermaid
graph TD
    Browser[Browser / index.html on S3] -->|POST /trigger| APIGW[API Gateway HTTP API]
    Browser -->|GET /status?execution_arn=...| APIGW
    APIGW -->|Lambda proxy| TL[trigger_lambda.py]
    APIGW -->|Lambda proxy| SL[status_lambda.py]
    TL -->|StartExecution| SFN[Step Functions: RedTeamMainOrchestrator]
    SL -->|DescribeExecution| SFN
    SL -->|GetObject runs/{run_id}/summary.json| S3[S3: autoredteam-artifacts-664261903713]
```

### AWS Services

| Service | Role |
|---|---|
| S3 (static hosting) | Serves `index.html` to the browser |
| API Gateway HTTP API | Routes `/trigger` and `/status` to Lambda |
| Lambda (trigger) | Starts Step Functions execution, returns `execution_arn` + `run_id` |
| Lambda (status) | Polls Step Functions, reads S3 summary when complete |
| Step Functions | `RedTeamMainOrchestrator` — the existing pipeline |
| S3 (artifacts) | `autoredteam-artifacts-664261903713` — stores `runs/{run_id}/summary.json` |

---

## Components and Interfaces

### trigger_lambda.py

**Handler**: `trigger_lambda.lambda_handler`

**Trigger**: `POST /trigger` (no request body required)

**Logic**:
1. Handle `OPTIONS` → return 200 + CORS headers
2. Read `STATE_MACHINE_ARN` from `os.environ`; return 500 if missing/empty
3. Generate `run_id = f"run-{date}-{hex6}"` where date is `YYYYMMDD` UTC and hex6 is 6 random hex chars
4. Generate `timestamp` as current UTC ISO8601 string
5. Call `sfn.start_execution(stateMachineArn=..., input=json.dumps({run_id, timestamp}))`
6. Return 200 `{execution_arn, run_id}` on success; 500 `{error}` on any exception

**Environment Variables**:
- `STATE_MACHINE_ARN` — ARN of `RedTeamMainOrchestrator`

**Response shape (success)**:
```json
{ "execution_arn": "arn:aws:states:...", "run_id": "run-20240115-a3f9c2" }
```

**Response shape (error)**:
```json
{ "error": "STATE_MACHINE_ARN not configured" }
```

---

### status_lambda.py

**Handler**: `status_lambda.lambda_handler`

**Trigger**: `GET /status?execution_arn=<arn>`

**Logic**:
1. Handle `OPTIONS` → return 200 + CORS headers
2. Extract `execution_arn` from query string; return 400 if absent
3. Call `sfn.describe_execution(executionArn=execution_arn)`
4. Build response with `status`, `start_date`, `stop_date`, `execution_arn`
5. If `status == "SUCCEEDED"`:
   - Parse `run_id` from execution `input` JSON
   - Try `s3.get_object(Bucket=ARTIFACT_BUCKET, Key=f"runs/{run_id}/summary.json")`
   - If found: include parsed JSON as `summary`
   - If `NoSuchKey`: include `summary: null`
6. Return 200 with full response; 500 on unexpected exceptions

**Environment Variables**:
- `ARTIFACT_BUCKET` — `autoredteam-artifacts-664261903713`

**Response shape (running)**:
```json
{
  "execution_arn": "arn:...",
  "status": "RUNNING",
  "start_date": "2024-01-15T10:30:00+00:00",
  "stop_date": null,
  "summary": null
}
```

**Response shape (succeeded with summary)**:
```json
{
  "execution_arn": "arn:...",
  "status": "SUCCEEDED",
  "start_date": "2024-01-15T10:30:00+00:00",
  "stop_date": "2024-01-15T10:35:00+00:00",
  "summary": {
    "run_id": "run-20240115-a3f9c2",
    "status": "COMPLETE",
    "completed_at": "...",
    "promotions": 1,
    "terminal_successes": 0,
    "failures": 0,
    "lanes": [...]
  }
}
```

---

### index.html

**Hosting**: S3 static website or any HTTP server

**Structure** (all inline, no external deps):
- Single `<script>` block with all JS
- Single `<style>` block with all CSS
- `const API_BASE = "https://YOUR_API_ID.execute-api.us-west-2.amazonaws.com/prod"` at top of script — the only value operators need to change

**UI States**:

| State | Button | Lane Cards | Summary Panel |
|---|---|---|---|
| Idle | Enabled | 3 lanes, "Idle" | Hidden |
| Running | Disabled | 3 lanes, "In Progress" + elapsed | Hidden |
| Succeeded | Enabled | 3 lanes with results | Visible |
| Failed/Aborted | Enabled | 3 lanes with results | Visible (error) |
| Poll error | Enabled (after 10 errors) | Last known state | Error banner |

**Polling logic**:
- Start: `setInterval(poll, 5000)` after successful trigger
- Stop: when status is `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or `ABORTED`
- Error handling: increment consecutive error counter; stop and show persistent error at 10
- Retry for missing summary: if `status === "SUCCEEDED"` and `summary === null`, retry once after 3 seconds

**Lane card rendering**:
- Always shows all three lanes: `OBJ_WEB_BYPASS`, `OBJ_IDENTITY_ESCALATION`, `OBJ_WAF_BYPASS`
- `terminal_status === "TERMINAL_SUCCESS"` → green highlight + "✓ Terminal Success" badge
- `outcome === "FAILED"` → red highlight + error message
- `phi_score` formatted to 2 decimal places

---

## Data Models

### Execution Input (sent to Step Functions)

```json
{
  "run_id": "run-20240115-a3f9c2",
  "timestamp": "2024-01-15T10:30:00.000000+00:00"
}
```

### Run Summary (read from S3 `runs/{run_id}/summary.json`)

```json
{
  "run_id": "run-20240115-a3f9c2",
  "timestamp": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:35:00Z",
  "status": "COMPLETE",
  "lane_count": 3,
  "promotions": 1,
  "terminal_successes": 0,
  "failures": 0,
  "lanes": [
    {
      "lane_id": "OBJ_WEB_BYPASS",
      "outcome": "SUCCESS",
      "phi_score": 0.72,
      "terminal_status": "ACTIVE",
      "error": null
    },
    {
      "lane_id": "OBJ_IDENTITY_ESCALATION",
      "outcome": "FAILED",
      "phi_score": 0.0,
      "terminal_status": "ACTIVE",
      "error": "DVWAUnreachableError"
    },
    {
      "lane_id": "OBJ_WAF_BYPASS",
      "outcome": "SUCCESS",
      "phi_score": 0.55,
      "terminal_status": "ACTIVE",
      "error": null
    }
  ]
}
```

### IAM Policy — Trigger Lambda Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "states:StartExecution",
      "Resource": "arn:aws:states:us-west-2:664261903713:stateMachine:RedTeamMainOrchestrator"
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

### IAM Policy — Status Lambda Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "states:DescribeExecution",
      "Resource": "arn:aws:states:us-west-2:664261903713:execution:RedTeamMainOrchestrator:*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::autoredteam-artifacts-664261903713/runs/*"
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Button state reflects execution status

*For any* dashboard state object, the "Run Red Team" button SHALL be enabled if and only if no execution is currently in progress (i.e., `state.running === false`).

**Validates: Requirements 1.1, 1.6**

---

### Property 2: run_id format correctness

*For any* invocation of `trigger_lambda`, the generated `run_id` SHALL match the regex pattern `^run-\d{8}-[0-9a-f]{6}$` where the 8-digit segment is a valid UTC date in `YYYYMMDD` format.

**Validates: Requirements 1.3, 4.2**

---

### Property 3: Trigger Lambda error responses always include non-empty error string

*For any* exception raised during `StartExecution` (network error, IAM error, invalid ARN, etc.), the Lambda response SHALL have HTTP status 500 and the response body SHALL contain an `error` field with a non-empty string value.

**Validates: Requirements 1.5**

---

### Property 4: Trigger Lambda CORS headers on all responses

*For any* invocation of `trigger_lambda` — whether the result is a 200 success, 500 error, or 200 OPTIONS preflight — the response headers SHALL include `Access-Control-Allow-Origin: *`.

**Validates: Requirements 4.4, 4.5**

---

### Property 5: Status Lambda response completeness

*For any* valid `execution_arn` passed to `status_lambda`, the response body SHALL contain all four fields: `status`, `start_date`, `stop_date`, and `execution_arn`.

**Validates: Requirements 5.2**

---

### Property 6: Status Lambda CORS headers on all responses

*For any* invocation of `status_lambda` — whether the result is a 200 success, 400 missing parameter, 500 error, or 200 OPTIONS preflight — the response headers SHALL include `Access-Control-Allow-Origin: *`.

**Validates: Requirements 5.5**

---

### Property 7: S3 key construction from run_id

*For any* `run_id` value extracted from a succeeded execution's input payload, the S3 key used to fetch the summary SHALL be exactly `runs/{run_id}/summary.json` against the `ARTIFACT_BUCKET`.

**Validates: Requirements 3.1, 5.3**

---

### Property 8: Terminal status stops polling

*For any* status value in `{SUCCEEDED, FAILED, TIMED_OUT, ABORTED}` returned by the status endpoint, the dashboard SHALL clear the polling interval and transition out of the running state.

**Validates: Requirements 2.4**

---

### Property 9: Consecutive error retry limit

*For any* sequence of N consecutive HTTP errors from the status endpoint where N < 10, the dashboard SHALL continue polling. When N reaches 10, the dashboard SHALL stop polling and display a persistent error message.

**Validates: Requirements 2.5, 2.6**

---

### Property 10: Results panel lane card count matches summary

*For any* run summary JSON containing N lane entries in the `lanes` array, the rendered results panel SHALL display exactly N lane cards.

**Validates: Requirements 3.2**

---

### Property 11: Lane card styling reflects lane outcome

*For any* lane entry where `terminal_status === "TERMINAL_SUCCESS"`, the rendered card SHALL include a success visual indicator. *For any* lane entry where `outcome === "FAILED"`, the rendered card SHALL include an error visual indicator and display the `error` field value.

**Validates: Requirements 3.3, 3.4**

---

### Property 12: Summary section contains all required fields

*For any* valid run summary JSON, the rendered summary section SHALL display `status`, `run_id`, `completed_at`, `promotions`, `terminal_successes`, and `failures`.

**Validates: Requirements 3.5**

---

### Property 13: Lane names always visible

*For any* dashboard state (idle, running, or completed), the rendered HTML SHALL contain all three lane identifiers: `OBJ_WEB_BYPASS`, `OBJ_IDENTITY_ESCALATION`, and `OBJ_WAF_BYPASS`.

**Validates: Requirements 7.3**

---

## Error Handling

| Failure | Handler | Outcome |
|---|---|---|
| `STATE_MACHINE_ARN` env var missing | `trigger_lambda` | HTTP 500, `{"error": "STATE_MACHINE_ARN not configured"}` |
| `StartExecution` raises any exception | `trigger_lambda` | HTTP 500, `{"error": str(e)}` |
| `execution_arn` query param absent | `status_lambda` | HTTP 400, `{"error": "execution_arn parameter required"}` |
| `DescribeExecution` raises exception | `status_lambda` | HTTP 500, `{"error": str(e)}` |
| S3 `NoSuchKey` for summary | `status_lambda` | HTTP 200, `summary: null` |
| `ARTIFACT_BUCKET` env var missing | `status_lambda` | HTTP 500, `{"error": "ARTIFACT_BUCKET not configured"}` |
| Dashboard fetch error (< 10 consecutive) | `index.html` | Inline error banner, polling continues |
| Dashboard fetch error (10 consecutive) | `index.html` | Persistent error, polling stops |
| Summary null after SUCCEEDED | `index.html` | "Fetching results…" message, single retry after 3s |

---

## Testing Strategy

This feature is primarily composed of:
- Two thin Lambda functions (pure request/response logic with boto3 calls)
- A single-file HTML/JS frontend (UI state machine + DOM rendering)

PBT is applicable to the Lambda functions (pure logic, input variation matters) and to the JavaScript state/rendering logic. The API Gateway configuration and IAM policies are infrastructure — tested via smoke checks.

### Property-Based Testing

**Library**: [`hypothesis`](https://hypothesis.readthedocs.io/) for Python Lambdas; [`fast-check`](https://fast-check.dev/) for JavaScript frontend logic.

Each property test runs a minimum of **100 iterations**.

Tag format: `# Feature: redteam-ui-dashboard, Property {N}: {description}`

**Python (trigger_lambda, status_lambda)**:
- Property 2: Generate random invocation timestamps, verify `run_id` format
- Property 3: Generate random exception types/messages, verify 500 + non-empty error
- Property 4: Invoke via all code paths (success, error, OPTIONS), verify CORS header present
- Property 5: Mock `describe_execution` with random status/date values, verify all four fields present
- Property 6: Same as Property 4 for status_lambda
- Property 7: Generate random `run_id` strings, verify S3 key = `runs/{run_id}/summary.json`

**JavaScript (index.html logic)**:
- Property 1: Generate random state objects, verify button enabled === !state.running
- Property 8: Generate random terminal status strings, verify polling stops
- Property 9: Generate N consecutive errors (0–15), verify polling continues for N<10, stops at N=10
- Property 10: Generate summary JSON with N lanes (0–10), verify N cards rendered
- Property 11: Generate lane objects with varying outcome/terminal_status, verify correct CSS class applied
- Property 12: Generate random summary JSON, verify all 6 required fields appear in rendered output
- Property 13: For any state, verify all three lane names present in DOM

### Unit / Example Tests

- Trigger Lambda: OPTIONS preflight returns 200 + CORS
- Trigger Lambda: missing `STATE_MACHINE_ARN` returns 500 with correct message
- Status Lambda: missing `execution_arn` param returns 400 with correct message
- Status Lambda: `NoSuchKey` from S3 returns `summary: null` (not an error)
- Status Lambda: `SUCCEEDED` status triggers S3 read; `RUNNING` does not
- Dashboard: initial page load shows idle state with button enabled
- Dashboard: `summary: null` after SUCCEEDED shows "Fetching results…"

### Smoke Tests (Console verification)

- API Gateway has routes `POST /trigger` and `GET /status` deployed to `prod` stage
- Both Lambda functions exist with correct runtime (Python 3.12) and handler
- IAM roles have correct least-privilege policies attached
- S3 bucket has static website hosting enabled and `index.html` is publicly accessible

---

## Console Deployment Guide

### Step 1: Create Trigger Lambda IAM Role

1. Go to **IAM → Roles → Create role**
2. Trusted entity: **AWS service → Lambda**
3. Skip attaching managed policies — click through to **Create role**
4. Name: `RedTeamTriggerLambdaRole`
5. After creation, open the role → **Add permissions → Create inline policy**
6. Switch to JSON tab and paste the Trigger Lambda IAM policy from the Data Models section above
7. Name the policy `RedTeamTriggerPolicy` → **Create policy**

### Step 2: Create Status Lambda IAM Role

1. Repeat Step 1 with name `RedTeamStatusLambdaRole`
2. Paste the Status Lambda IAM policy from the Data Models section
3. Name the policy `RedTeamStatusPolicy`

### Step 3: Create trigger_lambda

1. Go to **Lambda → Create function → Author from scratch**
2. Function name: `redteam-trigger`
3. Runtime: **Python 3.12**
4. Execution role: **Use an existing role → RedTeamTriggerLambdaRole**
5. Click **Create function**
6. In the code editor, replace the default code with the contents of `src/dashboard/trigger_lambda.py`
7. Click **Deploy**
8. Go to **Configuration → Environment variables → Edit**
9. Add: `STATE_MACHINE_ARN` = `arn:aws:states:us-west-2:664261903713:stateMachine:RedTeamMainOrchestrator`
10. Click **Save**
11. Under **Configuration → General configuration**, set timeout to **30 seconds**

### Step 4: Create status_lambda

1. Repeat Step 3 with:
   - Function name: `redteam-status`
   - Execution role: `RedTeamStatusLambdaRole`
   - Code: contents of `src/dashboard/status_lambda.py`
   - Environment variable: `ARTIFACT_BUCKET` = `autoredteam-artifacts-664261903713`

### Step 5: Create API Gateway HTTP API

1. Go to **API Gateway → Create API → HTTP API → Build**
2. Click **Add integration**:
   - Integration type: **Lambda**
   - Lambda function: `redteam-trigger`
3. API name: `redteam-dashboard-api`
4. Click **Next**
5. Add routes:
   - `POST /trigger` → `redteam-trigger`
   - `GET /status` → `redteam-status`
6. Click **Next → Next → Create**
7. Note the **Invoke URL** (e.g., `https://abc123.execute-api.us-west-2.amazonaws.com`)

### Step 6: Enable CORS on API Gateway

1. Open the API → **CORS → Configure**
2. Access-Control-Allow-Origin: `*`
3. Access-Control-Allow-Methods: `GET, POST, OPTIONS`
4. Access-Control-Allow-Headers: `Content-Type`
5. Click **Save**

### Step 7: Deploy to prod stage

1. Go to **Deploy → Stages**
2. The default stage `$default` is auto-deployed; rename or create a `prod` stage if needed
3. The full base URL will be: `https://{api-id}.execute-api.us-west-2.amazonaws.com/prod`

### Step 8: Update index.html and host on S3

1. Open `src/dashboard/index.html`
2. Find the line: `const API_BASE = "https://YOUR_API_ID.execute-api.us-west-2.amazonaws.com/prod";`
3. Replace with your actual API Gateway URL from Step 5
4. Go to **S3 → Create bucket** (or use an existing bucket)
   - Uncheck "Block all public access"
   - Enable **Static website hosting** under Properties
   - Index document: `index.html`
5. Upload `index.html`
6. Set the object's ACL to **public-read** (or add a bucket policy allowing `s3:GetObject` for `*`)
7. Open the **Static website hosting** endpoint URL in your browser

### Step 9: Verify end-to-end

1. Open the dashboard URL
2. Click **Run Red Team** — button should disable and show "Running"
3. Wait ~30 seconds, then check the Step Functions console for the new execution
4. After the execution completes, the dashboard should show lane results
