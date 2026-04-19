# Requirements Document

## Introduction

The RedTeam UI Dashboard is a single-page web application that provides operators with a browser-based interface to trigger and monitor the Lambda RedTeam Harness pipeline. The dashboard allows users to launch a Step Functions execution of the `RedTeamMainOrchestrator` state machine, observe live execution status across the three attack lanes (OBJ_WEB_BYPASS, OBJ_IDENTITY_ESCALATION, OBJ_WAF_BYPASS), and review the final run summary including per-lane Phi scores, gate outcomes, and terminal statuses once the pipeline completes.

The backend consists of two Lambda functions exposed via API Gateway: one to trigger a new execution and one to poll execution status and retrieve results from S3. The frontend is a static HTML/JS file hosted on S3 with public access, requiring no build toolchain.

## Glossary

- **Dashboard**: The single-page HTML/JS web application served from S3.
- **Trigger_Lambda**: The AWS Lambda function that starts a new Step Functions execution of `RedTeamMainOrchestrator`.
- **Status_Lambda**: The AWS Lambda function that queries Step Functions for execution status and reads the run summary from S3.
- **API_Gateway**: The Amazon API Gateway HTTP API that exposes `Trigger_Lambda` and `Status_Lambda` as HTTP endpoints.
- **Execution**: A single run of the `RedTeamMainOrchestrator` Step Functions state machine.
- **Lane**: One of the three parallel attack objectives: `OBJ_WEB_BYPASS`, `OBJ_IDENTITY_ESCALATION`, or `OBJ_WAF_BYPASS`.
- **Phi_Score**: The composite quality score (0.0–1.0) computed per lane by the harness pipeline.
- **Run_Summary**: The JSON artifact written to S3 at `runs/{run_id}/summary.json` by the `run-summarizer` Lambda.
- **Execution_ARN**: The Amazon Resource Name uniquely identifying a Step Functions execution.
- **Poll_Interval**: The fixed interval (in seconds) at which the Dashboard re-queries execution status.
- **CORS**: Cross-Origin Resource Sharing headers required for browser-to-API communication.

---

## Requirements

### Requirement 1: Trigger Execution via API

**User Story:** As an operator, I want to click a "Run Red Team" button in the browser, so that I can start a new pipeline execution without needing AWS console access or CLI credentials.

#### Acceptance Criteria

1. THE Dashboard SHALL render a "Run Red Team" button that is enabled when no execution is currently in progress.
2. WHEN the "Run Red Team" button is clicked, THE Dashboard SHALL send an HTTP POST request to the `API_Gateway` trigger endpoint.
3. WHEN the trigger endpoint receives a POST request, THE Trigger_Lambda SHALL call `StartExecution` on the `RedTeamMainOrchestrator` Step Functions state machine with a generated `run_id` and ISO8601 `timestamp` as input payload.
4. WHEN `StartExecution` succeeds, THE Trigger_Lambda SHALL return an HTTP 200 response containing the `execution_arn` and `run_id`.
5. IF `StartExecution` fails, THEN THE Trigger_Lambda SHALL return an HTTP 500 response containing a non-empty `error` string.
6. WHILE an execution is in progress, THE Dashboard SHALL disable the "Run Red Team" button and display a status indicator showing the execution is running.

---

### Requirement 2: Live Status Polling

**User Story:** As an operator, I want the dashboard to automatically refresh execution status, so that I can see real-time progress without manually reloading the page.

#### Acceptance Criteria

1. WHEN an execution is started, THE Dashboard SHALL begin polling the `API_Gateway` status endpoint at a fixed `Poll_Interval` of 5 seconds.
2. WHEN the status endpoint receives a GET request with an `execution_arn` parameter, THE Status_Lambda SHALL call `DescribeExecution` on Step Functions and return the current status string (`RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or `ABORTED`).
3. WHILE the execution status is `RUNNING`, THE Dashboard SHALL display the elapsed time since execution start and the current status for each Lane as "In Progress".
4. WHEN the execution status transitions to `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or `ABORTED`, THE Dashboard SHALL stop polling and transition to the results view.
5. IF the status endpoint returns an HTTP error, THEN THE Dashboard SHALL display an inline error message and continue polling until the maximum retry count of 10 consecutive errors is reached.
6. WHEN 10 consecutive polling errors occur, THE Dashboard SHALL stop polling and display a persistent error message with the last known status.

---

### Requirement 3: Results Dashboard

**User Story:** As an operator, I want to see a structured results view after the pipeline completes, so that I can evaluate lane outcomes, Phi scores, and whether any lane achieved terminal success.

#### Acceptance Criteria

1. WHEN the execution status is `SUCCEEDED`, THE Status_Lambda SHALL read `runs/{run_id}/summary.json` from the S3 artifact bucket and include its contents in the status response.
2. WHEN the run summary is available, THE Dashboard SHALL display a results panel containing one card per Lane showing: `lane_id`, `outcome`, `phi_score` (formatted to two decimal places), and `terminal_status`.
3. WHEN a Lane's `terminal_status` is `TERMINAL_SUCCESS`, THE Dashboard SHALL visually distinguish that lane card (e.g., green highlight or success badge).
4. WHEN a Lane's `outcome` is `FAILED`, THE Dashboard SHALL visually distinguish that lane card (e.g., red highlight or error badge) and display the `error` field if present.
5. THE Dashboard SHALL display the overall run `status`, `run_id`, `completed_at` timestamp, and aggregate counts (`promotions`, `terminal_successes`, `failures`) from the run summary.
6. IF the execution status is `SUCCEEDED` but the S3 summary file is not yet available, THEN THE Status_Lambda SHALL return the execution status without summary data, and THE Dashboard SHALL display a "Fetching results…" message and retry once after 3 seconds.

---

### Requirement 4: Backend Lambda — Trigger

**User Story:** As a developer, I want a minimal Lambda function that starts Step Functions executions, so that the frontend has a secure, CORS-enabled HTTP endpoint to call.

#### Acceptance Criteria

1. THE Trigger_Lambda SHALL be implemented in Python 3.12 and deployable as a single-file ZIP artifact.
2. THE Trigger_Lambda SHALL generate a `run_id` using the format `run-{YYYYMMDD}-{6-char-hex}` derived from the current UTC date and a random hex suffix.
3. WHEN invoked, THE Trigger_Lambda SHALL read the Step Functions state machine ARN from the `STATE_MACHINE_ARN` environment variable.
4. THE Trigger_Lambda SHALL return CORS headers (`Access-Control-Allow-Origin: *`) on all responses including error responses.
5. THE Trigger_Lambda SHALL handle `OPTIONS` preflight requests by returning HTTP 200 with the required CORS headers.
6. IF the `STATE_MACHINE_ARN` environment variable is absent or empty, THEN THE Trigger_Lambda SHALL return HTTP 500 with error message `"STATE_MACHINE_ARN not configured"`.

---

### Requirement 5: Backend Lambda — Status

**User Story:** As a developer, I want a minimal Lambda function that returns execution status and run summary data, so that the frontend can display live and final results.

#### Acceptance Criteria

1. THE Status_Lambda SHALL be implemented in Python 3.12 and deployable as a single-file ZIP artifact.
2. WHEN invoked with a query parameter `execution_arn`, THE Status_Lambda SHALL call `DescribeExecution` and return `status`, `start_date`, `stop_date`, and `execution_arn` in the response body.
3. WHEN the execution status is `SUCCEEDED`, THE Status_Lambda SHALL attempt to read the run summary from S3 using the `run_id` extracted from the execution input payload.
4. THE Status_Lambda SHALL read the S3 artifact bucket name from the `ARTIFACT_BUCKET` environment variable.
5. THE Status_Lambda SHALL return CORS headers (`Access-Control-Allow-Origin: *`) on all responses including error responses.
6. IF the `execution_arn` query parameter is absent, THEN THE Status_Lambda SHALL return HTTP 400 with error message `"execution_arn parameter required"`.
7. IF the S3 summary file does not exist, THEN THE Status_Lambda SHALL return the execution status with `summary: null` rather than returning an error.

---

### Requirement 6: API Gateway Configuration

**User Story:** As a developer, I want an API Gateway HTTP API with two routes, so that the frontend can reach both Lambda functions from a browser.

#### Acceptance Criteria

1. THE API_Gateway SHALL expose a `POST /trigger` route integrated with `Trigger_Lambda`.
2. THE API_Gateway SHALL expose a `GET /status` route integrated with `Status_Lambda`.
3. THE API_Gateway SHALL be configured with CORS to allow `Origin: *`, `Methods: GET, POST, OPTIONS`, and `Headers: Content-Type`.
4. THE API_Gateway SHALL be deployed to a stage named `prod`.
5. WHERE the API_Gateway is configured with Lambda proxy integration, THE API_Gateway SHALL pass the full request context to each Lambda function.

---

### Requirement 7: Frontend Single-Page Application

**User Story:** As an operator, I want a self-contained HTML file I can open in a browser or host on S3, so that I can use the dashboard without installing any tools or running a build step.

#### Acceptance Criteria

1. THE Dashboard SHALL be implemented as a single `index.html` file containing all HTML, CSS, and JavaScript inline with no external dependencies beyond browser-native APIs.
2. THE Dashboard SHALL read the API base URL from a JavaScript constant at the top of the file so that operators can update it without modifying application logic.
3. THE Dashboard SHALL display the three Lane names (`OBJ_WEB_BYPASS`, `OBJ_IDENTITY_ESCALATION`, `OBJ_WAF_BYPASS`) in the status area at all times, updating their state as polling progresses.
4. THE Dashboard SHALL display a timestamp of the last successful poll response.
5. WHEN the page is loaded, THE Dashboard SHALL display the idle state with the "Run Red Team" button enabled and no execution in progress.
6. THE Dashboard SHALL be renderable in modern browsers (Chrome, Firefox, Safari, Edge) without requiring any browser extensions or plugins.

---

### Requirement 8: IAM Permissions

**User Story:** As a developer, I want each Lambda function to have a least-privilege IAM role, so that the system follows AWS security best practices.

#### Acceptance Criteria

1. THE Trigger_Lambda execution role SHALL include `states:StartExecution` permission scoped to the `RedTeamMainOrchestrator` state machine ARN.
2. THE Status_Lambda execution role SHALL include `states:DescribeExecution` permission scoped to the `RedTeamMainOrchestrator` state machine ARN.
3. THE Status_Lambda execution role SHALL include `s3:GetObject` permission scoped to the `autoredteam-artifacts-664261903713` bucket and the `runs/*` key prefix.
4. THE Trigger_Lambda execution role SHALL include `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` permissions for CloudWatch Logs.
5. THE Status_Lambda execution role SHALL include `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` permissions for CloudWatch Logs.

---

### Requirement 9: Console Deployment Guidance

**User Story:** As a developer operating in a federated AWS environment without CLI credentials, I want step-by-step console instructions for deploying all backend components, so that I can set up the system entirely through the AWS Management Console.

#### Acceptance Criteria

1. THE deployment guide SHALL provide numbered steps for creating the `Trigger_Lambda` function via the AWS Lambda console, including runtime, handler, environment variable, and IAM role configuration.
2. THE deployment guide SHALL provide numbered steps for creating the `Status_Lambda` function via the AWS Lambda console, including runtime, handler, environment variable, and IAM role configuration.
3. THE deployment guide SHALL provide numbered steps for creating the `API_Gateway` HTTP API, adding both routes, configuring Lambda integrations, enabling CORS, and deploying to the `prod` stage.
4. THE deployment guide SHALL provide instructions for updating the API base URL constant in `index.html` and uploading the file to an S3 bucket configured for static website hosting.
5. THE deployment guide SHALL specify the exact IAM policy JSON for each Lambda execution role so that operators can paste it directly into the console.
