# Manual Parameter Store Setup (Federated AWS Access)

Since you're using federated AWS access for the hackathon and don't have CLI credentials, you'll need to create parameters manually via the AWS Console.

## Quick Start: Minimum 6 Critical Parameters

These are the absolute minimum parameters needed to test the orchestrator:

### Step 1: Open AWS Systems Manager Parameter Store
1. Go to AWS Console → **Systems Manager**
2. In left sidebar, click **Parameter Store**
3. Click **Create parameter** button

### Step 2: Create Each Parameter

For each parameter below, click "Create parameter" and fill in:

#### Parameter 1: Schedule Expression
- **Name**: `/autoredteam/prod/schedule_expression`
- **Type**: `String`
- **Value**: `rate(5 minutes)`
- Click **Create parameter**

#### Parameter 2: Active Lanes
- **Name**: `/autoredteam/prod/active_lanes`
- **Type**: `String`
- **Value**: `["OBJ_WEB_BYPASS","OBJ_IDENTITY_ESCALATION","OBJ_WAF_BYPASS"]`
- Click **Create parameter**

#### Parameter 3: Bedrock Model ID
- **Name**: `/autoredteam/prod/bedrock_model_id`
- **Type**: `String`
- **Value**: `amazon.nova-pro-v1:0`
- Click **Create parameter**

#### Parameter 4: Map Max Concurrency
- **Name**: `/autoredteam/prod/map_max_concurrency`
- **Type**: `String`
- **Value**: `10`
- Click **Create parameter**

#### Parameter 5: DVWA Admin Username
- **Name**: `/autoredteam/prod/dvwa/admin_username`
- **Type**: `String`
- **Value**: `admin`
- Click **Create parameter**

#### Parameter 6: DVWA Admin Password
- **Name**: `/autoredteam/prod/dvwa/admin_password`
- **Type**: `SecureString` ⚠️ (Important: Select SecureString, not String)
- **Value**: `password`
- Click **Create parameter**

---

## Test After Creating These 6 Parameters

After creating these 6 parameters:

1. Go to **Lambda** → `orchestrator-init` function
2. Click **Test** tab
3. Create a test event with this JSON:
```json
{
  "execution_id": "test-123",
  "scheduled_time": "2026-04-19T12:00:00Z"
}
```
4. Click **Test** button
5. Check if it runs without `ParameterNotFound` errors

---

## Full Parameter List (57 Total)

If the test works with the 6 critical parameters above, you'll need to create the remaining 51 parameters for full functionality. Here's the complete list organized by category:

### OBJ_WEB_BYPASS Lane (18 parameters)

| Parameter Name | Type | Value |
|----------------|------|-------|
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/target_url` | String | `http://10.0.1.192/dvwa` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/dvwa_security_level` | String | `low` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/terminal_condition` | String | `{"lane_type":"WEB_BYPASS","success_indicator":"Welcome to the password protected area"}` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/phi_weights/alpha` | String | `0.6` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/phi_weights/beta` | String | `0.25` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/phi_weights/gamma` | String | `0.15` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/reproducibility_min_fraction` | String | `0.8` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/reproducibility_reruns` | String | `3` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/evidence_markers` | String | `["Welcome to the password"]` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/cost_max_tokens` | String | `50000` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/cost_max_duration_ms` | String | `240000` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/gate_thresholds/noise_patterns` | String | `["Login required","DVWA default page"]` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/bedrock_max_retries` | String | `3` |
| `/autoredteam/prod/lanes/OBJ_WEB_BYPASS/http_timeout_ms` | String | `10000` |

### OBJ_IDENTITY_ESCALATION Lane (18 parameters)

| Parameter Name | Type | Value |
|----------------|------|-------|
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/target_url` | String | `http://10.0.1.192/dvwa` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/dvwa_security_level` | String | `low` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/terminal_condition` | String | `{"lane_type":"IDENTITY_ESCALATION","privilege_string":"You have an unseen message","admin_session_marker":"admin"}` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/alpha` | String | `0.6` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/beta` | String | `0.25` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/gamma` | String | `0.15` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/reproducibility_min_fraction` | String | `0.8` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/reproducibility_reruns` | String | `3` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/evidence_markers` | String | `["unseen message"]` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/cost_max_tokens` | String | `50000` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/cost_max_duration_ms` | String | `240000` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/noise_patterns` | String | `["Login required"]` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/bedrock_max_retries` | String | `3` |
| `/autoredteam/prod/lanes/OBJ_IDENTITY_ESCALATION/http_timeout_ms` | String | `10000` |

### OBJ_WAF_BYPASS Lane (18 parameters)

| Parameter Name | Type | Value |
|----------------|------|-------|
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/target_url` | String | `http://10.0.1.192/dvwa` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/dvwa_security_level` | String | `medium` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/terminal_condition` | String | `{"lane_type":"WAF_BYPASS","waf_block_indicator":"That request was blocked","interpretation_markers":["You have an error in your SQL syntax","mysql_fetch_array","<script>alert(","uid="]}` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/phi_weights/alpha` | String | `0.6` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/phi_weights/beta` | String | `0.25` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/phi_weights/gamma` | String | `0.15` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/reproducibility_min_fraction` | String | `0.8` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/reproducibility_reruns` | String | `3` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/evidence_markers` | String | `["SQL syntax","mysql_fetch"]` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/cost_max_tokens` | String | `50000` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/cost_max_duration_ms` | String | `240000` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/gate_thresholds/noise_patterns` | String | `["Login required","That request was blocked"]` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/bedrock_max_retries` | String | `3` |
| `/autoredteam/prod/lanes/OBJ_WAF_BYPASS/http_timeout_ms` | String | `10000` |

---

## Tips for Faster Manual Entry

1. **Copy-paste values carefully** - JSON values must be exact (no extra spaces)
2. **Double-check SecureString** - Only the password parameter should be SecureString
3. **Create in batches** - Do the 6 critical ones first, test, then do the rest
4. **Use browser tabs** - Open Parameter Store in multiple tabs to speed up creation

---

## What Happens Next

After creating all parameters:

1. **Test orchestrator-init Lambda** - Should initialize without errors
2. **Test Step Functions manually** - Run `RedTeamMainOrchestrator` with test input
3. **Check S3 bucket** - Results will be written to your S3 bucket
4. **Monitor CloudWatch Logs** - Check logs for each Lambda function

---

## Troubleshooting

**If you get "Access Denied" errors:**
- Your IAM role needs `ssm:PutParameter` permission
- Check if your hackathon role has Systems Manager access

**If parameters don't show up:**
- Verify you're in the correct region (us-west-2)
- Check the parameter name exactly matches (case-sensitive)

**If you want to delete and start over:**
- Select all parameters with prefix `/autoredteam/prod/`
- Click **Delete** button
