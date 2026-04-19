#!/usr/bin/env python3
"""
seed_parameters.py — Populate all required SSM Parameter Store paths
for the AutoRedTeam Lambda Harness demo environment.

Usage:
    python infra/seed_parameters.py --env dev --dvwa-ip 10.0.1.50

This script is idempotent: running it multiple times will overwrite
existing parameters with the same values.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3


def seed(env: str, dvwa_ip: str, dvwa_password: str = "password") -> None:
    ssm = boto3.client("ssm")
    prefix = f"/autoredteam/{env}"

    params: list[tuple[str, str, str]] = [
        # Global
        (f"{prefix}/schedule_expression", "rate(5 minutes)", "String"),
        (f"{prefix}/active_lanes", json.dumps([
            "OBJ_WEB_BYPASS",
            "OBJ_IDENTITY_ESCALATION",
            "OBJ_WAF_BYPASS",
        ]), "String"),
        (f"{prefix}/bedrock_model_id",
         "amazon.nova-pro-v1:0", "String"),
        (f"{prefix}/map_max_concurrency", "10", "String"),
        (f"{prefix}/dvwa/admin_username", "admin", "String"),
        (f"{prefix}/dvwa/admin_password", dvwa_password, "SecureString"),

        # OBJ_WEB_BYPASS
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/target_url",
         f"http://{dvwa_ip}/dvwa", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/dvwa_security_level", "low", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/terminal_condition", json.dumps({
            "lane_type": "WEB_BYPASS",
            "success_indicator": "Welcome to the password protected area",
        }), "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/phi_weights/alpha", "0.6", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/phi_weights/beta", "0.25", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/phi_weights/gamma", "0.15", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/gate_thresholds/reproducibility_min_fraction",
         "0.8", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/gate_thresholds/reproducibility_reruns",
         "3", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/gate_thresholds/evidence_markers",
         json.dumps(["Welcome to the password"]), "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/gate_thresholds/cost_max_tokens",
         "50000", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/gate_thresholds/cost_max_duration_ms",
         "240000", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/gate_thresholds/noise_patterns",
         json.dumps(["Login required", "DVWA default page"]), "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/bedrock_max_retries", "3", "String"),
        (f"{prefix}/lanes/OBJ_WEB_BYPASS/http_timeout_ms", "10000", "String"),

        # OBJ_IDENTITY_ESCALATION
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/target_url",
         f"http://{dvwa_ip}/dvwa", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/dvwa_security_level", "low", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/terminal_condition", json.dumps({
            "lane_type": "IDENTITY_ESCALATION",
            "privilege_string": "You have an unseen message",
            "admin_session_marker": "admin",
        }), "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/alpha", "0.6", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/beta", "0.25", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/phi_weights/gamma", "0.15", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/reproducibility_min_fraction",
         "0.8", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/reproducibility_reruns",
         "3", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/evidence_markers",
         json.dumps(["unseen message"]), "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/cost_max_tokens",
         "50000", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/cost_max_duration_ms",
         "240000", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/gate_thresholds/noise_patterns",
         json.dumps(["Login required"]), "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/bedrock_max_retries", "3", "String"),
        (f"{prefix}/lanes/OBJ_IDENTITY_ESCALATION/http_timeout_ms", "10000", "String"),

        # OBJ_WAF_BYPASS
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/target_url",
         f"http://{dvwa_ip}/dvwa", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/dvwa_security_level", "medium", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/terminal_condition", json.dumps({
            "lane_type": "WAF_BYPASS",
            "waf_block_indicator": "That request was blocked",
            "interpretation_markers": [
                "You have an error in your SQL syntax",
                "mysql_fetch_array",
                "<script>alert(",
                "uid=",
            ],
        }), "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/phi_weights/alpha", "0.6", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/phi_weights/beta", "0.25", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/phi_weights/gamma", "0.15", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/gate_thresholds/reproducibility_min_fraction",
         "0.8", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/gate_thresholds/reproducibility_reruns",
         "3", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/gate_thresholds/evidence_markers",
         json.dumps(["SQL syntax", "mysql_fetch"]), "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/gate_thresholds/cost_max_tokens",
         "50000", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/gate_thresholds/cost_max_duration_ms",
         "240000", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/gate_thresholds/noise_patterns",
         json.dumps(["Login required", "That request was blocked"]), "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/bedrock_max_retries", "3", "String"),
        (f"{prefix}/lanes/OBJ_WAF_BYPASS/http_timeout_ms", "10000", "String"),
    ]

    print(f"Seeding {len(params)} parameters under prefix '{prefix}'...")
    for name, value, param_type in params:
        ssm.put_parameter(
            Name=name,
            Value=value,
            Type=param_type,
            Overwrite=True,
        )
        print(f"  ✓ {name}")

    print(f"\nDone. {len(params)} parameters written to SSM.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed AutoRedTeam SSM parameters")
    parser.add_argument("--env", default="dev", help="Environment name (dev/staging/prod)")
    parser.add_argument("--dvwa-ip", required=True, help="Private IP of the DVWA EC2 instance")
    parser.add_argument("--dvwa-password", default="password",
                        help="DVWA admin password (stored as SecureString)")
    args = parser.parse_args()

    seed(env=args.env, dvwa_ip=args.dvwa_ip, dvwa_password=args.dvwa_password)


if __name__ == "__main__":
    main()
