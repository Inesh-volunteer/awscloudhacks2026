# AWS Console Deployment Guide
## Lambda RedTeam Harness

This guide walks you through deploying the Lambda RedTeam Harness using the AWS Console (web interface). No command-line experience required!

## 🚀 Quick Start for Hackathons

**Recommended workflow:**
1. **Steps 1-3**: Set up Bedrock, S3, and DynamoDB (5 minutes)
2. **Steps 5-6**: Deploy VPC and get DVWA IP address (10 minutes) 
3. **Step 4**: Run automated parameter setup script (2 minutes)
4. **Steps 7-9**: Create Lambda functions, Step Functions, and scheduler (15 minutes)

**💡 Pro tip**: Use the automated seed script in Step 4 instead of manual parameter creation - it saves 30+ minutes!

## Prerequisites

1. **AWS Account** with administrative access
2. **Bedrock Access** - You'll need to enable Amazon Nova Pro or another Amazon model in your AWS region
3. **Basic AWS Console familiarity** - knowing how to navigate and click buttons

---

## Step 1: Enable Amazon Bedrock

### 1.1 Navigate to Bedrock
1. Log into AWS Console
2. In the search bar at the top, type "Bedrock" and click on "Amazon Bedrock"
3. Make sure you're in a supported region (us-east-1, us-west-2, or eu-west-1 recommended)

### 1.2 Enable Model Access (Updated for Current Console)
1. In the left sidebar, click "Foundation models"
2. Look for **Amazon** models in the list (not Anthropic/Claude)
3. Find and enable one of these Amazon models:
   - **Amazon Nova Pro** (recommended for hackathons - latest model)
   - **Amazon Nova Lite** (faster, good for testing)
   - **Amazon Titan Text G1 - Express** (reliable fallback)
4. Click on your chosen model and click "Enable" or "Request access"
5. Wait for approval (usually instant for Amazon models)

**Note:** Write down the exact model ID (e.g., `amazon.nova-pro-v1:0`) - you'll need this later!

### 1.3 Amazon Model Compatibility (Perfect for Hackathons!)
The system is designed to work with Amazon's latest models, which are ideal for hackathons:
- **Amazon Nova Pro**: Best for complex red-team scenarios, supports advanced reasoning (recommended)
- **Amazon Nova Lite**: Faster responses, good for high-volume testing  
- **Amazon Titan Text**: Reliable baseline model

**Hackathon Benefits:**
- Amazon models are typically pre-approved and available immediately
- No need to request access to third-party models (Claude, etc.)
- Consistent performance and availability during events
- All Amazon models use the same API format, so you can switch easily

All Amazon models use the same API format, so the system will work with any of them by just changing the model ID in Parameter Store.

---

## Step 2: Create S3 Bucket

### 2.1 Navigate to S3
1. In AWS Console search bar, type "S3" and click on it
2. Click "Create bucket" (orange button)

### 2.2 Configure Bucket
1. **Bucket name**: Enter something unique like `your-name-redteam-artifacts-2024`
2. **Region**: Choose the same region where you enabled Bedrock
3. **Versioning**: Scroll down and check "Enable" under "Bucket Versioning"
4. Leave all other settings as default
5. Click "Create bucket" at the bottom

### 2.3 Note Your Bucket Name
Write down your bucket name - you'll need it later!

---

## Step 3: Create DynamoDB Tables

### 3.1 Create ObjectiveLanes Table
1. Search for "DynamoDB" in AWS Console
2. Click "Create table"
3. **Table name**: `ObjectiveLanes`
4. **Partition key**: `lane_id` (String)
5. Leave "Sort key" empty
6. Click "Create table"

### 3.2 Create Runs Table
1. Click "Create table" again
2. **Table name**: `Runs`
3. **Partition key**: `run_id` (String)
4. Leave "Sort key" empty
5. Click "Create table"

---

## Step 4: Set Up Parameter Store (Recommended: Use Seed Script)

**⚠️ WORKFLOW NOTE**: You can do this step now OR after Steps 5-6. If you want to use the automated seed script (recommended), you'll need the DVWA IP address from Step 5 first.

### 4.1 Navigate to Systems Manager
1. Search for "Systems Manager" in AWS Console
2. In the left sidebar, click "Parameter Store"

### 4.2 Recommended Approach: Use the Automated Seed Script

**💡 RECOMMENDED FOR HACKATHONS**: Skip manual parameter creation and use our automated script!

The system needs 50+ parameters configured. Instead of creating them manually, use the included seed script:

#### Prerequisites for Seed Script:
1. **Complete Steps 5-6 first** to get your DVWA IP address
2. **Install Python dependencies**:
   ```bash
   pip install boto3
   ```

#### Run the Seed Script:
1. **Get your DVWA IP address** (you'll get this after Step 5):
   - It will be something like `10.0.1.50`
   - Write it down for now

2. **Run the script** (after you have the DVWA IP):
   ```bash
   python3 infra/seed_parameters.py --env prod --dvwa-ip YOUR_DVWA_IP_HERE
   ```
   
   Example:
   ```bash
   python3 infra/seed_parameters.py --env prod --dvwa-ip 10.0.1.50
   ```

3. **What it does**:
   - Creates all 50+ parameters automatically
   - Uses Amazon Nova Pro model by default
   - Sets up all 3 lanes with proper configurations
   - Configures realistic thresholds and weights for demo

4. **Verify it worked**:
   - Go to Parameter Store in AWS Console
   - You should see all the `/autoredteam/prod/` parameters created

**✅ If you use the seed script, skip to Step 5!**

### 4.3 Alternative: Manual Parameter Creation (Advanced Users Only)

If you prefer to create parameters manually or want to understand the configuration:
### 4.3.1 Create Global Parameters

**Global Parameters:**
- Name: `/autoredteam/prod/schedule_expression`
  Value: `cron(0 */6 * * ? *)`

- Name: `/autoredteam/prod/active_lanes`
  Value: `["OBJ_WEB_BYPASS","OBJ_IDENTITY_ESCALATION","OBJ_WAF_BYPASS"]`

- Name: `/autoredteam/prod/bedrock_model_id`
  Value: `amazon.nova-pro-v1:0` (or whichever Amazon model you enabled)

- Name: `/autoredteam/prod/map_max_concurrency`
  Value: `3`

**DVWA Credentials:**
- Name: `/autoredteam/prod/dvwa/admin_username`
  Value: `admin`

- Name: `/autoredteam/prod/dvwa/admin_password` (use SecureString type)
  Value: `password`

**Lane-Specific Parameters** (create these for each lane):

**For OBJ_WEB_BYPASS lane:**
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/target_url`: `http://10.0.1.50/dvwa`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/dvwa_security_level`: `low`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/terminal_condition`: `{"lane_type": "WEB_BYPASS", "success_indicator": "Welcome to the password protected area"}`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/phi_weights/alpha`: `0.4`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/phi_weights/beta`: `0.35`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/phi_weights/gamma`: `0.25`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/reproducibility_min_fraction`: `0.8`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/reproducibility_reruns`: `3`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/evidence_markers`: `["SQL syntax", "mysql_fetch"]`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/cost_max_tokens`: `50000`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/cost_max_duration_ms`: `240000`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/noise_patterns`: `["DVWA default page", "Login required"]`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/bedrock_max_retries`: `3`
- `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/http_timeout_ms`: `10000`

**For OBJ_IDENTITY_ESCALATION lane:**
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/target_url`: `http://10.0.1.50/dvwa`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/dvwa_security_level`: `medium`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/terminal_condition`: `{"lane_type": "IDENTITY_ESCALATION", "privilege_string": "admin", "admin_session_marker": "admin_user"}`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/alpha`: `0.5`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/beta`: `0.3`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/gamma`: `0.2`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/reproducibility_min_fraction`: `0.8`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/reproducibility_reruns`: `3`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/evidence_markers`: `["privilege", "escalation", "admin"]`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/cost_max_tokens`: `50000`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/cost_max_duration_ms`: `240000`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/noise_patterns`: `["DVWA default page", "Login required"]`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/bedrock_max_retries`: `3`
- `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/http_timeout_ms`: `10000`

**For OBJ_WAF_BYPASS lane:**
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/target_url`: `http://10.0.1.50/dvwa`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/dvwa_security_level`: `high`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/terminal_condition`: `{"lane_type": "WAF_BYPASS", "waf_block_indicator": "blocked", "interpretation_markers": ["SQL error", "XSS executed", "command output"]}`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/phi_weights/alpha`: `0.3`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/phi_weights/beta`: `0.4`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/phi_weights/gamma`: `0.3`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/reproducibility_min_fraction`: `0.8`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/reproducibility_reruns`: `3`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/evidence_markers`: `["bypass", "filter", "payload"]`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/cost_max_tokens`: `50000`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/cost_max_duration_ms`: `240000`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/noise_patterns`: `["DVWA default page", "Login required"]`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/bedrock_max_retries`: `3`
- `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/http_timeout_ms`: `10000`

**💡 Pro Tip:** This is a lot of parameters! That's why we recommend using the automated seed script in section 4.2 above.

---

## Step 5: Create VPC and EC2 (DVWA Target)

### 5.1 Deploy VPC CloudFormation
1. Search for "CloudFormation" in AWS Console
2. Click "Create stack" → "With new resources"
3. Choose "Upload a template file"
4. Click "Choose file" and select `infra/cloudformation/vpc_and_ec2.yaml`
5. Click "Next"
6. **Stack name**: `redteam-vpc-stack`
7. Leave parameters as default (or customize if needed)
8. Click "Next" twice, check the acknowledgment box, then "Create stack"
9. Wait for stack to complete (5-10 minutes)

### 5.2 Note the EC2 Private IP
1. Once stack is complete, go to "Outputs" tab
2. Note the `DVWAPrivateIP` value - you'll need this for Lambda configuration

---

## Step 6: Create Lambda Functions

### 6.1 Get the Lambda Code (Two Options)

**Option A: If You Have the Repository**
If you have the full repository cloned locally:
1. The Lambda code is already in the `src/` folder
2. You'll need to create ZIP files for deployment (see packaging instructions below)

**Option B: For Hackathon Quick Setup (Recommended)**
Since you're following this deployment guide, you likely need the pre-built Lambda deployment packages:

1. **Download the pre-built Lambda packages** (these should be provided with the hackathon materials)
2. **Or create minimal Lambda functions** for testing:
   - We can start with simple "Hello World" Lambda functions
   - Then update them with the actual code later
   - This gets the infrastructure working first

**Option C: Create ZIP Files from Source**
If you have access to the source code:

1. **Create a folder** on your computer called `lambda-packages`
2. **For each Lambda function**, create a ZIP file containing:
   - The entire `src/` folder (with all Python files)
   - Make sure the ZIP file structure looks like:
     ```
     lambda-package.zip
     ├── src/
     │   ├── lib/
     │   │   ├── bedrock_client.py
     │   │   ├── config_loader.py
     │   │   └── ... (other library files)
     │   └── workers/
     │       ├── orchestrator_init.py
     │       ├── lane_worker.py
     │       ├── reproducibility_runner.py
     │       └── run_summarizer.py
     ```

**💡 For Hackathon**: I recommend starting with Option B (minimal functions) to get the infrastructure working, then we can provide the actual code files.

### 6.2 Quick Start: Create Placeholder Lambda Functions

**For immediate deployment**, let's create the Lambda functions with placeholder code first, then update them later:

1. **Skip the ZIP file creation for now**
2. **Create the Lambda functions** with default "Hello World" code
3. **Set up the infrastructure** (IAM roles, environment variables, etc.)
4. **Update with actual code** once we have the source files

This approach gets your infrastructure working quickly for the hackathon!

### 6.3 Create IAM Role for Lambda
1. Search for "IAM" in AWS Console
2. Click "Roles" in left sidebar
3. Click "Create role"
4. Choose "AWS service" → "Lambda"
5. Click "Next"
6. Search for and attach these policies:
   - `AmazonBedrockFullAccess`
   - `AmazonS3FullAccess`
   - `AmazonDynamoDBFullAccess`
   - `AmazonSSMReadOnlyAccess`
   - `CloudWatchFullAccess`
   - `AWSStepFunctionsFullAccess`
   - `AWSLambdaVPCAccessExecutionRole`
7. Click "Next"
8. **Role name**: `RedTeamLambdaRole`
9. Click "Create role"

### 6.4 Create Lambda Functions
For each of the 4 Lambda functions, repeat these steps:

1. Search for "Lambda" in AWS Console
2. Click "Create function"
3. Choose "Author from scratch"
4. **Function name**: 
   - `redteam-orchestrator-init`
   - `redteam-lane-worker`
   - `redteam-reproducibility-runner`
   - `redteam-run-summarizer`
5. **Runtime**: Python 3.11
6. **Execution role**: Use existing role → `RedTeamLambdaRole`
7. Click "Create function"

### 6.5 Configure Lambda Functions (Start with Placeholder Code)
For each Lambda function:

1. **Create the function first** with default code (we'll update later)
2. In the function page, **skip uploading ZIP files for now**
3. **Set the Handler** (even though we're using placeholder code):
   - `lambda_function.lambda_handler` (default for now)
   - We'll change this to the correct handlers later:
     - `src.workers.orchestrator_init.handler`
     - `src.workers.lane_worker.handler`
     - `src.workers.reproducibility_runner.handler`
     - `src.workers.run_summarizer.handler`
4. Go to "Configuration" → "Environment variables"
5. Add these variables:
   - `ENV`: `prod`
   - `S3_BUCKET`: (your bucket name from Step 2)
   - `LAMBDA_TIMEOUT_MS`: `300000`

**💡 Next Steps**: Once we have the actual Lambda code files, we'll come back and update each function with the proper ZIP files and handlers.

### 6.6 Configure VPC (for lane-worker only)
1. Go to "Configuration" → "VPC"
2. Click "Edit"
3. Choose the VPC created in Step 5
4. Select private subnets
5. Select the Lambda security group
6. Click "Save"

---

## Step 7: Create Step Functions

### 7.1 Create Main Orchestrator
1. Search for "Step Functions" in AWS Console
2. Click "Create state machine"
3. Choose "Write your workflow in code"
4. Copy the contents of `infra/main_orchestrator.json`
5. Paste it into the Definition box
6. **Update Lambda ARNs**: Replace placeholder ARNs with your actual Lambda function ARNs
7. **State machine name**: `RedTeamMainOrchestrator`
8. **Execution role**: Create new role with default settings
9. Click "Create state machine"

### 7.2 Create Reproducibility Sub-Machine
1. Click "Create state machine" again
2. Choose "Write your workflow in code"
3. Copy contents of `infra/reproducibility_sfn.json`
4. Update Lambda ARNs as needed
5. **State machine name**: `RedTeamReproducibility`
6. **Type**: Express
7. Click "Create state machine"

---

## Step 8: Create EventBridge Scheduler

### 8.1 Navigate to EventBridge
1. Search for "EventBridge" in AWS Console
2. Click "Schedules" in left sidebar
3. Click "Create schedule"

### 8.2 Configure Schedule
1. **Schedule name**: `RedTeamScheduler`
2. **Schedule pattern**: Cron-based schedule
3. **Cron expression**: `cron(0 */6 * * ? *)`  (every 6 hours)
4. **Flexible time window**: Off
5. Click "Next"

### 8.3 Configure Target
1. **Target API**: AWS Step Functions StartExecution
2. **Step Functions state machine**: Select your `RedTeamMainOrchestrator`
3. **Input**: 
```json
{
  "run_id": "<aws.scheduler.execution-id>",
  "timestamp": "<aws.scheduler.scheduled-time>"
}
```
4. **Execution role**: Create new role
5. Click "Next" → "Create schedule"

---

## Step 9: Test the System

### 9.1 Manual Test
1. Go to Step Functions console
2. Click on `RedTeamMainOrchestrator`
3. Click "Start execution"
4. Use this input:
```json
{
  "run_id": "test-run-001",
  "timestamp": "2024-01-01T00:00:00Z"
}
```
5. Click "Start execution"
6. Watch the execution progress

### 9.2 Check Results
1. **CloudWatch Logs**: Search for log groups starting with `/aws/lambda/redteam-`
2. **S3 Bucket**: Check for artifacts under `runs/test-run-001/`
3. **DynamoDB**: Check the `ObjectiveLanes` and `Runs` tables for data

---

## Troubleshooting

### Common Issues:

**"Access Denied" errors:**
- Check that your IAM role has all required permissions
- Verify Amazon model access is enabled (not just requested)
- Make sure you're using an Amazon model ID, not Anthropic/Claude

**"Function not found" errors:**
- Double-check Lambda function names in Step Functions definitions
- Ensure ARNs are correct

**VPC connectivity issues:**
- Verify security groups allow traffic between Lambda and EC2
- Check that EC2 instance is running DVWA on port 80

**Parameter Store errors:**
- Verify all required parameters are created with correct names
- Check parameter values are valid JSON where expected
- If using the seed script, ensure you have `boto3` installed: `pip install boto3`
- If seed script fails, check your AWS credentials are configured correctly

### Getting Help:
- Check CloudWatch Logs for detailed error messages
- Use AWS Support if you have a support plan
- Review the requirements.md and design.md files for system details

---

## Next Steps

Once deployed successfully:
1. Monitor the system through CloudWatch dashboards
2. Adjust parameters in Parameter Store to tune behavior
3. Review experiment results in S3
4. Scale up by adding more objective lanes

Congratulations! Your Lambda RedTeam Harness is now running autonomous red-team experiments! 🎉