# AgentRed: Autonomous LLM Red Team Harness

**AWS CloudHacks Hackathon Submission**

An automated red team testing framework that uses LLM agents to discover and exploit vulnerabilities in web applications, with a real-time dashboard for monitoring attack campaigns.

## 🎯 Project Overview

AgentRed is a serverless AWS-native system that orchestrates autonomous LLM-powered security testing across multiple attack objectives. The system runs parallel attack lanes, evaluates success using formal correctness properties, and provides operators with a browser-based dashboard to trigger and monitor campaigns.

**Live Dashboard:** [http://redteam-dashboard-ui.s3-website-us-west-2.amazonaws.com/]

## 🏗️ Architecture

### High-Level System Design

```
┌─────────────────────────────────────────────────────────────────┐
│                     Browser Dashboard (S3)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ OBJ_WEB_     │  │ OBJ_IDENTITY_│  │ OBJ_WAF_     │         │
│  │ BYPASS       │  │ ESCALATION   │  │ BYPASS       │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  API Gateway     │
                    │  (HTTP API)      │
                    └──────────────────┘
                         │         │
              ┌──────────┘         └──────────┐
              ▼                                ▼
    ┌─────────────────┐              ┌─────────────────┐
    │ Trigger Lambda  │              │ Status Lambda   │
    │ (Python 3.12)   │              │ (Python 3.12)   │
    └─────────────────┘              └─────────────────┘
              │                                │
              ▼                                ▼
    ┌─────────────────────────────────────────────────┐
    │     Step Functions: RedTeamMainOrchestrator     │
    │  ┌──────────────────────────────────────────┐  │
    │  │  Parallel Execution (Map State)          │  │
    │  │  ┌────────┐ ┌────────┐ ┌────────┐       │  │
    │  │  │ Lane 1 │ │ Lane 2 │ │ Lane 3 │       │  │
    │  │  └────────┘ └────────┘ └────────┘       │  │
    │  └──────────────────────────────────────────┘  │
    └─────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │ Lane Worker │  │ Phi Scorer  │  │ Summarizer  │
    │   Lambda    │  │   Lambda    │  │   Lambda    │
    └─────────────┘  └─────────────┘  └─────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  S3 Artifacts    │
                    │  runs/{run_id}/  │
                    └──────────────────┘
```

### AWS Services Used

| Service | Purpose |
|---------|---------|
| **Lambda** | Serverless compute for trigger, status, lane workers, scoring, and summarization |
| **Step Functions** | Orchestrates parallel attack lanes and manages execution flow |
| **API Gateway** | HTTP API exposing trigger and status endpoints |
| **S3** | Stores run artifacts (summaries, logs) and hosts static dashboard |
| **EC2** | Runs DVWA (Damn Vulnerable Web Application) target |
| **VPC** | Isolated network for target application |
| **IAM** | Least-privilege roles for each Lambda function |
| **CloudWatch Logs** | Centralized logging for all Lambda executions |

## ✨ Key Features

### 1. Autonomous LLM Agents
- Each attack lane runs an independent LLM agent with tool-calling capabilities
- Agents can browse web pages, submit forms, analyze responses, and adapt strategies
- Uses Anthropic Claude via AWS Bedrock

### 2. Parallel Attack Lanes
- **OBJ_WEB_BYPASS**: SQL injection, XSS, command injection
- **OBJ_IDENTITY_ESCALATION**: Authentication bypass, privilege escalation
- **OBJ_WAF_BYPASS**: WAF evasion techniques

### 3. Property-Based Testing
- Formal correctness properties validate attack success
- Uses Hypothesis (Python) and fast-check (JavaScript) for property testing
- Phi scoring system (0.0–1.0) measures attack quality

### 4. Real-Time Dashboard
- Single-page application with live polling
- Displays per-lane results, phi scores, and terminal status
- No build toolchain required — pure HTML/CSS/JS

### 5. Reproducibility
- Every run generates a unique `run_id`
- All artifacts stored in S3 for post-analysis
- Execution history preserved in Step Functions

## 📁 Repository Structure

```
.
├── src/
│   ├── dashboard/
│   │   ├── index.html           # Dashboard UI
│   │   ├── trigger_lambda.py    # Starts Step Functions execution
│   │   └── status_lambda.py     # Polls execution status + S3 results
│   └── lambda/
│       ├── lane_worker.py       # LLM agent execution per lane
│       ├── phi_scorer.py        # Computes attack quality scores
│       └── run_summarizer.py    # Aggregates results
├── infra/
│   ├── main_orchestrator.json   # Step Functions state machine
│   └── cloudformation/
│       └── vpc_and_ec2.yaml     # Target infrastructure
├── tests/
│   ├── test_trigger_lambda.py   # Property tests for trigger
│   ├── test_status_lambda.py    # Property tests for status
│   └── dashboard.test.js        # Property tests for UI logic
├── DEPLOYMENT_GUIDE.md          # Step-by-step AWS console deployment
└── README.md                    # This file
```

## 🚀 Deployment

### Prerequisites
- AWS Account with console access
- Python 3.12
- Node.js (for running JS tests)

### Quick Start

1. **Deploy IAM Roles**
   - Create `RedTeamTriggerLambdaRole` and `RedTeamStatusLambdaRole`
   - Attach policies from `DEPLOYMENT_GUIDE.md`

2. **Deploy Lambda Functions**
   ```bash
   cd src/dashboard
   zip trigger_lambda.zip trigger_lambda.py
   zip status_lambda.zip status_lambda.py
   ```
   - Upload via AWS Lambda console
   - Set environment variables (see `DEPLOYMENT_GUIDE.md`)

3. **Create API Gateway**
   - HTTP API with routes: `POST /trigger`, `GET /status`
   - Enable CORS

4. **Deploy Dashboard**
   - Create S3 bucket with static website hosting
   - Upload `index.html`
   - Add bucket policy for public read access

5. **Deploy Step Functions**
   - Create state machine from `infra/main_orchestrator.json`
   - Deploy target EC2 instance using `infra/cloudformation/vpc_and_ec2.yaml`

**Full deployment instructions:** See `DEPLOYMENT_GUIDE.md`

## 🧪 Testing

### Python Tests (Hypothesis)
```bash
pytest tests/test_trigger_lambda.py tests/test_status_lambda.py
```

### JavaScript Tests (fast-check + Jest)
```bash
npm install
npm test
```

### Property Coverage
- ✅ Run ID format correctness
- ✅ CORS headers on all response paths
- ✅ Error handling with non-empty error messages
- ✅ S3 key construction from run_id
- ✅ Terminal status detection
- ✅ Consecutive error retry limits
- ✅ Lane card rendering correctness
- ✅ Summary field completeness

## 📊 Sample Output

```json
{
  "run_id": "run-20260419-a3f9c2",
  "status": "COMPLETE",
  "completed_at": "2026-04-19T10:35:00Z",
  "promotions": 1,
  "terminal_successes": 0,
  "failures": 0,
  "lanes": [
    {
      "lane_id": "OBJ_WEB_BYPASS",
      "outcome": "SUCCESS",
      "phi_score": 0.72,
      "terminal_status": "ACTIVE"
    }
  ]
}
```

## 🔒 Security Considerations

- All Lambda functions use least-privilege IAM roles
- Target application runs in isolated VPC
- Dashboard uses CORS to restrict API access
- No AWS credentials stored in frontend code
- All artifacts encrypted at rest in S3

## 🎓 What I Learned

- Orchestrating complex serverless workflows with Step Functions
- Property-based testing for distributed systems
- Building browser-based dashboards with no build toolchain
- IAM policy design for least-privilege access
- Real-time polling patterns for async operations

## 🏆 Hackathon Highlights

- **100% serverless** — no EC2 management for core logic
- **Console-deployable** — no CLI required
- **Property-tested** — formal correctness guarantees
- **Production-ready** — comprehensive error handling and logging

## 📝 License

MIT

## 🙏 Acknowledgments

Built for AWS CloudHacks Hackathon 2026
