# Requirements Document

## Introduction

The AutoRedTeam Lambda Harness is a serverless research system that automates adversarial red-teaming experiments against a target web application (DVWA on EC2). The system uses an EventBridge Scheduler to trigger AWS Step Functions, which fan out parallel Lambda workers across multiple objective lanes. Each worker uses Amazon Bedrock (Converse API) to propose attack mutations, executes them against DVWA, and evaluates results using a keep/discard ratchet. Artifacts are stored in S3, operational state in DynamoDB, and configuration in AWS Parameter Store.

## Glossary

- **Harness**: The overall AutoRedTeam system orchestrating red-team experiments.
- **Objective_Lane**: A named attack objective (e.g., OBJ_WEB_BYPASS, OBJ_IDENTITY_ESCALATION, OBJ_WAF_BYPASS) processed independently in parallel.
- **Worker**: An AWS Lambda function that executes one full experiment cycle for a single Objective_Lane.
- **Strategy**: A structured artifact (stored in S3) representing an attack approach for a given Objective_Lane, including mutation history and metadata.
- **Mutation**: A Bedrock-proposed modification to the current Strategy, representing a new attack variant to test.
- **Experiment**: A single execution of a Mutation against the DVWA target, producing raw HTTP response data.
- **Terminal_Validator**: A binary function T_i that determines whether an Objective_Lane's terminal success condition has been met.
- **Phi_Function**: A scalar potential function Φ_i computed as a weighted sum of goal likelihood, precondition completion, and exploit depth scores.
- **Gate**: A binary pass/fail check (reproducibility, evidence quality, cost, noise) that must pass before a Strategy is promoted.
- **Ratchet**: The keep/discard mechanism that promotes a Mutation to the current Strategy only when all Gates pass and Φ_i improves.
- **DVWA**: Damn Vulnerable Web Application, an intentionally vulnerable PHP/MySQL web app running on an EC2 instance, used as the demo attack target.
- **Orchestrator**: The AWS Step Functions state machine that manages parallel lane execution.
- **Scheduler**: The Amazon EventBridge Scheduler rule that triggers the Orchestrator on a defined cadence.
- **Artifact_Store**: The Amazon S3 bucket used to persist Strategy files and experiment evidence.
- **State_Store**: The Amazon DynamoDB table used to track per-lane operational state, run metadata, and Ratchet history.
- **Config_Store**: AWS Systems Manager Parameter Store, used to hold objective definitions, gate thresholds, and Phi weights.
- **Bedrock_Client**: The Amazon Bedrock Converse API integration used by the Worker to propose Mutations and score results.

---

## Requirements

### Requirement 1: Scheduler-Triggered Orchestration

**User Story:** As a researcher, I want the red-team harness to run automatically on a schedule, so that experiments execute without manual intervention.

#### Acceptance Criteria

1. THE Scheduler SHALL trigger the Orchestrator on a configurable cron or rate expression stored in Config_Store.
2. WHEN the Scheduler fires, THE Orchestrator SHALL start a new Step Functions execution with a run identifier and timestamp payload.
3. IF the Orchestrator is already executing a previous run, THEN THE Scheduler SHALL allow the new execution to start independently without cancelling the prior run.
4. THE Orchestrator SHALL pass the list of active Objective_Lane identifiers to the parallel fan-out stage at execution start.

---

### Requirement 2: Parallel Objective Lane Execution

**User Story:** As a researcher, I want multiple attack objectives to run in parallel, so that the harness explores multiple threat vectors simultaneously within a single run.

#### Acceptance Criteria

1. THE Orchestrator SHALL execute all active Objective_Lanes concurrently using a Step Functions Inline Map state.
2. WHEN an Objective_Lane Worker fails with an unhandled error, THE Orchestrator SHALL mark that lane as failed and continue executing all remaining lanes.
3. THE Orchestrator SHALL collect per-lane results and write a consolidated run summary to the Artifact_Store upon completion of all lanes.
4. THE Orchestrator SHALL enforce a configurable maximum concurrency limit on the Inline Map, read from Config_Store.

---

### Requirement 3: Worker Initialization

**User Story:** As a researcher, I want each Worker to load its objective configuration at startup, so that lane-specific parameters drive the experiment without hardcoding.

#### Acceptance Criteria

1. WHEN a Worker starts, THE Worker SHALL load the Objective_Lane configuration (target URL, gate thresholds, Phi weights, terminal condition definition) from Config_Store using the lane identifier.
2. WHEN a Worker starts, THE Worker SHALL fetch the current best Strategy for the Objective_Lane from the Artifact_Store; IF no Strategy exists, THE Worker SHALL initialize a default seed Strategy.
3. IF Config_Store is unreachable, THEN THE Worker SHALL terminate with a structured error payload containing the lane identifier and failure reason.
4. THE Worker SHALL validate that all required configuration keys are present before proceeding; IF any key is missing, THE Worker SHALL terminate with a descriptive error.

---

### Requirement 4: Bedrock-Powered Mutation Planning

**User Story:** As a researcher, I want the Worker to use an LLM to propose attack mutations, so that the system explores novel attack variants beyond static payloads.

#### Acceptance Criteria

1. WHEN a Worker has loaded the current Strategy, THE Bedrock_Client SHALL receive a prompt containing the Objective_Lane definition, the current Strategy, and the last experiment result.
2. THE Bedrock_Client SHALL use the Amazon Bedrock Converse API with a configurable model identifier read from Config_Store.
3. WHEN the Bedrock_Client returns a response, THE Worker SHALL parse the response into a structured Mutation object containing: attack payload, target endpoint, HTTP method, headers, and a rationale string.
4. IF the Bedrock_Client returns a malformed or unparseable response, THEN THE Worker SHALL retry the request up to a configurable maximum retry count from Config_Store before terminating with an error.
5. THE Worker SHALL log the full Bedrock prompt and response to the Artifact_Store for audit purposes.

---

### Requirement 5: Experiment Execution Against DVWA

**User Story:** As a researcher, I want the Worker to execute the proposed Mutation against DVWA, so that real HTTP responses are collected as experiment evidence.

#### Acceptance Criteria

1. WHEN a Mutation is ready, THE Worker SHALL send the HTTP request defined by the Mutation (payload, endpoint, method, headers) to the DVWA target URL.
2. THE Worker SHALL capture the full HTTP response including status code, response headers, and response body as the Experiment result.
3. IF the DVWA target is unreachable or returns a connection error, THEN THE Worker SHALL record the failure in the State_Store and terminate the lane with a structured error.
4. THE Worker SHALL enforce a configurable HTTP request timeout (in milliseconds) read from Config_Store; IF the timeout is exceeded, THE Worker SHALL treat the request as a failed Experiment.
5. THE Worker SHALL store the raw Experiment result (request + response) as an artifact in the Artifact_Store under a key scoped to the run identifier and Objective_Lane.

---

### Requirement 6: Experiment Evaluation — Terminal Validator

**User Story:** As a researcher, I want the system to detect when an objective has been fully achieved, so that successful exploits are flagged and the lane can be marked complete.

#### Acceptance Criteria

1. WHEN an Experiment result is available, THE Terminal_Validator SHALL evaluate the result against the terminal success condition defined in the Objective_Lane configuration.
2. THE Terminal_Validator SHALL return a binary result: `true` if the terminal condition is met, `false` otherwise.
3. WHEN the Terminal_Validator returns `true`, THE Worker SHALL mark the Objective_Lane as `TERMINAL_SUCCESS` in the State_Store and promote the current Mutation to the Strategy without requiring Gate evaluation.
4. THE Worker SHALL record the terminal success evidence (Experiment result and Mutation) in the Artifact_Store.

---

### Requirement 7: Experiment Evaluation — Phi Function

**User Story:** As a researcher, I want a scalar progress score computed for each experiment, so that the Ratchet can make keep/discard decisions based on measurable improvement.

#### Acceptance Criteria

1. WHEN an Experiment result is available and the Terminal_Validator returns `false`, THE Worker SHALL invoke a separate Bedrock scoring call to derive the three Phi sub-scores: goal likelihood score (P_goal), precondition completion score (C_pre), and exploit depth score (D_depth).
2. THE scoring call SHALL use a structured prompt containing the Experiment result, the Objective_Lane rubric, and the current Strategy; THE Bedrock response SHALL be parsed into explicit numeric fields for P_goal, C_pre, and D_depth.
3. THE Phi_Function SHALL compute the final scalar score as: Φ_i = α_i × P_goal + β_i × C_pre + γ_i × D_depth, where weights α_i, β_i, γ_i are read per-lane from Config_Store.
4. THE Phi_Function SHALL produce a score in the range [0.0, 1.0].
5. THE Worker SHALL compare the new Phi_Function score against the score stored with the current Strategy in the State_Store.
6. IF the new Phi_Function score is less than or equal to the current Strategy score, THE Worker SHALL discard the Mutation and retain the existing Strategy without updating the State_Store.

---

### Requirement 8: Experiment Evaluation — Gates

**User Story:** As a researcher, I want gate checks to enforce quality standards before a mutation is promoted, so that only reproducible, evidenced, cost-efficient, and low-noise results advance.

#### Acceptance Criteria

1. WHEN the Phi_Function score improves over the current Strategy score, THE Worker SHALL trigger a nested Step Functions state machine to fan out reproducibility re-runs asynchronously, then evaluate all four Gates: reproducibility, evidence quality, cost, and noise.
2. THE Reproducibility_Gate SHALL be implemented as a nested Step Functions Inline Map that re-executes the Mutation against DVWA a configurable number of times in parallel; THE gate SHALL pass only if the terminal or Phi improvement is observed in a configurable minimum fraction of re-executions.
3. THE Evidence_Gate SHALL pass only if the Experiment result contains a configurable minimum set of evidence markers defined in the Objective_Lane configuration.
4. THE Cost_Gate SHALL pass only if the total Bedrock token usage and Lambda execution duration for the current cycle are within configurable thresholds read from Config_Store.
5. THE Noise_Gate SHALL pass only if the Experiment result does not match a configurable set of known-noisy response patterns defined in Config_Store.
6. IF any Gate fails, THE Worker SHALL discard the Mutation, record the failing Gate name and reason in the State_Store, and retain the existing Strategy.

---

### Requirement 9: Strategy Ratchet — Promote or Discard

**User Story:** As a researcher, I want the system to promote only improving, gate-passing mutations to the strategy, so that each lane's strategy monotonically improves over time.

#### Acceptance Criteria

1. WHEN all Gates pass and the Phi_Function score improves, THE Worker SHALL promote the Mutation by writing the new Strategy (including the Mutation, new Phi score, and Experiment evidence) to the Artifact_Store.
2. WHEN a Strategy is promoted, THE Worker SHALL update the State_Store record for the Objective_Lane with the new Phi score, promotion timestamp, and run identifier.
3. THE Worker SHALL append the promotion event to a per-lane history log in the Artifact_Store, preserving all prior Strategy versions.
4. WHEN a Mutation is discarded (Gate failure or no Phi improvement), THE Worker SHALL increment a discard counter in the State_Store for the Objective_Lane.
5. THE Artifact_Store key scheme for Strategy files SHALL be: `strategies/{lane_id}/current.json` for the active Strategy and `strategies/{lane_id}/history/{timestamp}.json` for archived versions.

---

### Requirement 10: State and Artifact Persistence

**User Story:** As a researcher, I want all run state and artifacts persisted durably, so that I can audit, replay, and analyze experiments after the fact.

#### Acceptance Criteria

1. THE State_Store SHALL maintain one record per Objective_Lane containing: current Phi score, terminal status, discard count, last run identifier, and last updated timestamp.
2. THE Artifact_Store SHALL store all Strategy files, Experiment results, Bedrock prompt/response logs, and run summaries under a consistent key hierarchy scoped by run identifier and lane identifier.
3. THE Worker SHALL write all State_Store updates atomically using DynamoDB conditional writes to prevent concurrent run conflicts.
4. THE Artifact_Store SHALL use S3 versioning so that no artifact is permanently overwritten.
5. WHEN a run completes, THE Orchestrator SHALL write a run summary JSON to the Artifact_Store at key `runs/{run_id}/summary.json` containing per-lane outcomes, Phi scores, and terminal statuses.

---

### Requirement 11: Configuration Management

**User Story:** As a researcher, I want all tunable parameters stored in Parameter Store, so that I can adjust thresholds and weights without redeploying code.

#### Acceptance Criteria

1. THE Config_Store SHALL hold the following parameter categories: schedule expression, active lane identifiers, per-lane objective definitions, Bedrock model identifier, Phi weights per lane, gate thresholds per lane, HTTP timeout, Bedrock retry count, and Inline Map concurrency limit.
2. THE Worker SHALL read all parameters from Config_Store at startup and cache them for the duration of the Lambda invocation.
3. IF a required parameter is absent from Config_Store, THEN THE Worker SHALL terminate with an error identifying the missing parameter path.
4. THE Harness SHALL namespace all Parameter Store paths under a configurable root prefix (e.g., `/autoredteam/{env}/`).

---

### Requirement 12: DVWA Target Infrastructure

**User Story:** As a researcher, I want DVWA running on a dedicated EC2 instance with per-lane security level control, so that I have a stable, isolated attack target for demo experiments.

#### Acceptance Criteria

1. THE Harness SHALL provision an EC2 instance running DVWA accessible over HTTP on port 80 within the same AWS VPC as the Lambda Workers.
2. THE EC2 instance SHALL use an Amazon Machine Image (AMI) or user-data script that installs and configures DVWA with a known default credential set stored in Config_Store.
3. THE Lambda Workers SHALL reach the DVWA EC2 instance via a private VPC endpoint or private IP address; THE Workers SHALL NOT require public internet access to reach DVWA.
4. THE EC2 instance security group SHALL allow inbound HTTP traffic only from the Lambda Worker security group.
5. WHERE the researcher enables the public demo mode, THE Harness SHALL expose DVWA via an Application Load Balancer with HTTPS termination.
6. EACH Worker SHALL set the DVWA security level for its Objective_Lane at initialization by calling the DVWA `/security.php` API endpoint with the lane-specific security level read from Config_Store (e.g., `low`, `medium`, `high`, `impossible`).
7. THE DVWA security level SHALL be configurable per Objective_Lane in Config_Store under the key `/autoredteam/{env}/lanes/{lane_id}/dvwa_security_level`.
8. AFTER setting the security level, THE Worker SHALL verify the level was applied by reading it back from the DVWA session before proceeding with the experiment.

---

### Requirement 14: Concrete Terminal Conditions per Objective Lane

**User Story:** As a researcher, I want each objective lane to have a precisely defined terminal success condition, so that the system can deterministically detect when an attack objective has been fully achieved.

#### Acceptance Criteria

**OBJ_WEB_BYPASS — Web Workflow Bypass:**
1. THE terminal condition SHALL be met when the Worker receives an HTTP response from DVWA that contains evidence of a protected action being invoked or an authorization boundary being crossed, specifically: the response body contains a success indicator string defined in Config_Store (e.g., a DVWA success message or a protected page title), AND the HTTP status code is 200.
2. THE terminal condition SHALL NOT be met by redirect responses (3xx) or error responses (4xx/5xx).
3. THE Worker SHALL extract and store the matched success indicator string as terminal evidence in the Artifact_Store.

**OBJ_IDENTITY_ESCALATION — Identity / Privilege Escalation:**
1. THE terminal condition SHALL be met when the Worker receives a DVWA response confirming that a privileged action has been executed under a non-admin session, specifically: the response body contains a privilege confirmation string (e.g., admin-only content or a role-change confirmation) defined in Config_Store, AND the session cookie used belongs to a non-privileged test account.
2. THE Worker SHALL record the session token, the privileged response body excerpt, and the HTTP request that triggered it as terminal evidence.
3. THE terminal condition SHALL NOT be met if the Worker is already authenticated as an admin user.

**OBJ_WAF_BYPASS — WAF / Parser Bypass:**
1. THE terminal condition SHALL be met when the Worker's payload is accepted and processed by the DVWA backend without being blocked, specifically: the response does not contain a WAF block indicator string defined in Config_Store, AND the response body contains evidence that the payload was interpreted (e.g., SQL error output, reflected XSS execution marker, or command output string).
2. THE Worker SHALL record the accepted payload, the response body excerpt, and the HTTP status code as terminal evidence.
3. THE terminal condition SHALL NOT be met if the response contains a WAF block indicator even if the status code is 200.

---

### Requirement 13: Observability and Logging

**User Story:** As a researcher, I want structured logs and metrics emitted throughout the pipeline, so that I can monitor experiment progress and diagnose failures.

#### Acceptance Criteria

1. THE Worker SHALL emit structured JSON logs to Amazon CloudWatch Logs for each major lifecycle event: initialization, Strategy fetch, Mutation proposal, Experiment execution, Gate evaluation, and Ratchet decision.
2. THE Orchestrator SHALL emit Step Functions execution events to CloudWatch Logs with X-Ray tracing enabled.
3. THE Worker SHALL publish a custom CloudWatch metric `RedTeam/PhiScore` per Objective_Lane after each Ratchet decision, tagged with lane identifier and run identifier.
4. THE Worker SHALL publish a custom CloudWatch metric `RedTeam/GateFailures` per Gate per Objective_Lane, incremented on each Gate failure.
5. IF a Worker Lambda invocation exceeds 80% of its configured timeout, THE Worker SHALL emit a `RedTeam/TimeoutWarning` CloudWatch metric.
