# Implementation Tasks: Lambda RedTeam Harness

## Task List

- [x] 1. Project scaffold and shared data models
  - [x] 1.1 Create directory structure (src/workers, src/lib, src/lib/evaluators, infra, tests)
  - [x] 1.2 Create requirements.txt with boto3, requests, hypothesis, moto, pytest
  - [x] 1.3 Implement shared data models (Mutation, ExperimentResult, Strategy, LaneConfig, PhiScores, GateResult, LaneState)

- [x] 2. Library: config_loader.py
  - [x] 2.1 Implement ConfigLoader with load_lane_config and load_global_config
  - [x] 2.2 Implement SSM batch read with caching and MissingConfigError
  - [x] 2.3 Write property tests (Properties 5, 6, 31, 32)

- [x] 3. Library: evaluators/phi_function.py
  - [x] 3.1 Implement PhiFunction.compute with weighted sum and [0,1] clamping
  - [x] 3.2 Write property tests (Property 19)

- [x] 4. Library: evaluators/terminal_validator.py
  - [x] 4.1 Implement TerminalValidator.evaluate with per-lane dispatch
  - [x] 4.2 Implement OBJ_WEB_BYPASS logic (status==200 + success_indicator in body)
  - [x] 4.3 Implement OBJ_IDENTITY_ESCALATION logic (privilege_string in body + non-admin session)
  - [x] 4.4 Implement OBJ_WAF_BYPASS logic (no block indicator + interpretation marker present)
  - [x] 4.5 Write property tests (Properties 15, 34, 35, 36)

- [x] 5. Library: evaluators/gates.py
  - [x] 5.1 Implement GateEvaluator.evaluate_evidence (marker containment check)
  - [x] 5.2 Implement GateEvaluator.evaluate_cost (token + duration threshold check)
  - [x] 5.3 Implement GateEvaluator.evaluate_noise (pattern exclusion check)
  - [x] 5.4 Write property tests (Properties 21, 22, 23, 24)

- [x] 6. Library: dvwa_client.py
  - [x] 6.1 Implement DVWAClient with session login on init
  - [x] 6.2 Implement set_security_level (POST to /security.php)
  - [x] 6.3 Implement verify_security_level (GET and parse current level)
  - [x] 6.4 Implement execute_request with timeout enforcement and full response capture
  - [x] 6.5 Write property tests (Properties 11, 12, 13, 33)

- [x] 7. Library: bedrock_client.py
  - [x] 7.1 Implement BedrockClient.propose_mutation with structured prompt and Mutation parsing
  - [x] 7.2 Implement BedrockClient.score_experiment with structured scoring prompt and PhiScores parsing
  - [x] 7.3 Implement retry logic (parse failures + exponential backoff on API errors)
  - [x] 7.4 Implement S3 audit log write for every Bedrock call
  - [x] 7.5 Write property tests (Properties 7, 8, 9, 10, 18)

- [x] 8. Library: strategy_store.py
  - [x] 8.1 Implement StrategyStore.get_current (S3 read, return None if absent)
  - [x] 8.2 Implement StrategyStore.promote (write current.json + archive to history/)
  - [x] 8.3 Implement seed strategy initialization
  - [x] 8.4 Write property tests (Properties 14, 26, 28)

- [x] 9. Library: state_store.py
  - [x] 9.1 Implement StateStore.get_lane_state (DynamoDB GetItem)
  - [x] 9.2 Implement StateStore.update_lane_state with conditional write
  - [x] 9.3 Implement StateStore.increment_discard_counter
  - [x] 9.4 Write property tests (Properties 20, 25, 27, 29, 30)

- [-] 10. Lambda: orchestrator-init
  - [x] 10.1 Implement handler: load active_lanes from SSM, return lane list with run_id
  - [x] 10.2 Write property tests (Properties 1, 2)

- [-] 11. Lambda: reproducibility-runner
  - [x] 11.1 Implement handler: execute mutation, run terminal check + phi scoring, return pass/fail
  - [x] 11.2 Write unit tests

- [-] 12. Lambda: lane-worker
  - [x] 12.1 Implement full 10-step lifecycle handler
  - [x] 12.2 Implement CloudWatch structured logging for all lifecycle events
  - [x] 12.3 Implement CloudWatch metric emission (PhiScore, GateFailures, TimeoutWarning)
  - [x] 12.4 Write property tests (Properties 3, 16, 17, 37, 38, 39)

- [-] 13. Lambda: run-summarizer
  - [x] 13.1 Implement handler: aggregate lane results, write runs/{run_id}/summary.json
  - [x] 13.2 Write property tests (Property 4)

- [-] 14. Step Functions: main orchestrator ASL
  - [x] 14.1 Write main_orchestrator.json (LoadObjectives → RunLanes Map → FinalizeCycle)
  - [x] 14.2 Add Catch on Map state for lane failure isolation

- [-] 15. Step Functions: reproducibility sub-machine ASL
  - [x] 15.1 Write reproducibility_sfn.json (RunReruns Map → AggregateResults → PassOrFail Choice)

- [-] 16. Infrastructure: EC2 DVWA setup
  - [x] 16.1 Write ec2_userdata.sh (install Docker, pull DVWA image, start container on port 80)
  - [x] 16.2 Write CloudFormation template for VPC, subnets, security groups, EC2 instance

- [ ] 17. Infrastructure: Lambda and IAM
  - [x] 17.1 Write CloudFormation template for Lambda functions with VPC config
  - [x] 17.2 Write IAM roles and policies (Bedrock, S3, DynamoDB, SSM, CloudWatch, SFN)

- [ ] 18. Infrastructure: DynamoDB, S3, EventBridge
  - [x] 18.1 Write CloudFormation for ObjectiveLanes and Runs DynamoDB tables
  - [x] 18.2 Write CloudFormation for S3 bucket with versioning
  - [x] 18.3 Write CloudFormation for EventBridge Scheduler rule

- [ ] 19. Parameter Store seed script
  - [x] 19.1 Write seed_parameters.py to populate all required SSM paths for demo environment
