# Tasks

## Task List

- [x] 1. Create trigger_lambda.py
  - [x] 1.1 Implement OPTIONS preflight handler returning 200 + CORS headers
  - [x] 1.2 Implement run_id generation matching format `run-{YYYYMMDD}-{6-char-hex}`
  - [x] 1.3 Read STATE_MACHINE_ARN from environment; return HTTP 500 if missing/empty
  - [x] 1.4 Call sfn.start_execution with run_id and ISO8601 timestamp as input payload
  - [x] 1.5 Return HTTP 200 with execution_arn and run_id on success
  - [x] 1.6 Return HTTP 500 with non-empty error string on any exception
  - [x] 1.7 Include Access-Control-Allow-Origin: * on all responses

- [x] 2. Create status_lambda.py
  - [x] 2.1 Implement OPTIONS preflight handler returning 200 + CORS headers
  - [x] 2.2 Return HTTP 400 if execution_arn query parameter is absent
  - [x] 2.3 Call sfn.describe_execution and return status, start_date, stop_date, execution_arn
  - [x] 2.4 When status is SUCCEEDED, extract run_id from execution input and read runs/{run_id}/summary.json from S3
  - [x] 2.5 Return summary: null (not an error) when S3 key does not exist
  - [x] 2.6 Read ARTIFACT_BUCKET from environment; return HTTP 500 if missing/empty
  - [x] 2.7 Include Access-Control-Allow-Origin: * on all responses

- [x] 3. Create index.html dashboard
  - [x] 3.1 Add API_BASE constant at top of script block for easy URL configuration
  - [x] 3.2 Render idle state on page load: button enabled, three lane cards visible, no summary panel
  - [x] 3.3 Implement trigger flow: POST /trigger, disable button, store execution_arn and run_id
  - [x] 3.4 Implement polling: setInterval at 5000ms, GET /status?execution_arn=..., display elapsed time
  - [x] 3.5 Stop polling and show results when status is SUCCEEDED, FAILED, TIMED_OUT, or ABORTED
  - [x] 3.6 Track consecutive poll errors; stop polling and show persistent error after 10 consecutive failures
  - [x] 3.7 Render lane cards with phi_score (2 decimal places), outcome, terminal_status
  - [x] 3.8 Apply green highlight/badge for TERMINAL_SUCCESS lanes; red highlight/error text for FAILED lanes
  - [x] 3.9 Render summary panel with status, run_id, completed_at, promotions, terminal_successes, failures
  - [x] 3.10 Show "Fetching results…" and retry once after 3s when status is SUCCEEDED but summary is null
  - [x] 3.11 Display last successful poll timestamp
  - [x] 3.12 Ensure all three lane names (OBJ_WEB_BYPASS, OBJ_IDENTITY_ESCALATION, OBJ_WAF_BYPASS) are always visible

- [-] 4. Write unit and property-based tests for trigger_lambda.py
  - [ ] 4.1 Property test: run_id format matches `^run-\d{8}-[0-9a-f]{6}$` for any invocation (Property 2)
  - [x] 4.2 Property test: any exception from StartExecution yields HTTP 500 with non-empty error (Property 3)
  - [x] 4.3 Property test: CORS header present on all response paths — success, error, OPTIONS (Property 4)
  - [x] 4.4 Example test: OPTIONS returns 200 with CORS headers
  - [x] 4.5 Example test: missing STATE_MACHINE_ARN returns 500 with message "STATE_MACHINE_ARN not configured"
  - [x] 4.6 Example test: successful StartExecution returns 200 with execution_arn and run_id

- [x] 5. Write unit and property-based tests for status_lambda.py
  - [x] 5.1 Property test: response always contains status, start_date, stop_date, execution_arn for any valid arn (Property 5)
  - [x] 5.2 Property test: CORS header present on all response paths (Property 6)
  - [x] 5.3 Property test: S3 key is always runs/{run_id}/summary.json for any run_id (Property 7)
  - [x] 5.4 Example test: missing execution_arn param returns 400 with correct message
  - [x] 5.5 Example test: S3 NoSuchKey returns summary: null (not an error response)
  - [x] 5.6 Example test: RUNNING status does not trigger S3 read

- [x] 6. Write tests for index.html JavaScript logic
  - [x] 6.1 Property test: button enabled === !state.running for any state object (Property 1)
  - [x] 6.2 Property test: any terminal status value stops polling (Property 8)
  - [x] 6.3 Property test: polling continues for N<10 errors, stops at N=10 (Property 9)
  - [x] 6.4 Property test: N lane entries in summary renders N lane cards (Property 10)
  - [x] 6.5 Property test: lane card CSS class reflects terminal_status and outcome (Property 11)
  - [x] 6.6 Property test: all 6 summary fields present in rendered output for any valid summary (Property 12)
  - [x] 6.7 Property test: all three lane names visible in DOM for any state (Property 13)
