#!/usr/bin/env python3
"""
Enterprise Application Downtime Analyzer using CloudWatch
EC2 + ECS
"""

import boto3
import traceback
from datetime import datetime, timedelta
from botocore.exceptions import ClientError, BotoCoreError

# ---------------- CUSTOM EXCEPTIONS ---------------- #

class AWSInitError(Exception): pass
class MetricFetchError(Exception): pass
class NoDataError(Exception): pass


# ---------------- INIT ---------------- #

def init_clients(region):
    try:
        cw = boto3.client("cloudwatch", region_name=region)
        return cw
    except Exception as e:
        traceback.print_exc()
        raise AWSInitError("Failed to initialize CloudWatch client") from e


# ============================================================
# EC2 APPLICATION DOWNTIME (StatusCheck or ALB metrics)
# ============================================================

def get_ec2_app_downtime(instance_id, region, start, end):
    cw = init_clients(region)

    try:
        response = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="StatusCheckFailed",
            Dimensions=[{"Name":"InstanceId","Value":instance_id}],
            StartTime=start,
            EndTime=end,
            Period=300,
            Statistics=["Sum"]
        )
    except (ClientError, BotoCoreError):
        traceback.print_exc()
        raise MetricFetchError("Failed to fetch EC2 CloudWatch metrics")

    datapoints = response.get("Datapoints", [])
    if not datapoints:
        raise NoDataError("No EC2 metric data found")

    downtime_minutes = sum(5 for d in datapoints if d["Sum"] > 0)
    downtime_hours = downtime_minutes / 60

    print("\n========== EC2 APPLICATION DOWNTIME REPORT ==========")
    print(f"Instance ID : {instance_id}")
    print(f"Period      : {start} -> {end}")
    print(f"Downtime    : {downtime_minutes} minutes ({downtime_hours:.2f} hrs)")

    if downtime_minutes == 0:
        print("✅ No EC2 application downtime detected")

    return downtime_minutes


# ============================================================
# ECS APPLICATION DOWNTIME (RunningTaskCount)
# ============================================================

def get_ecs_app_downtime(cluster, service, region, start, end):
    cw = init_clients(region)

    try:
        response = cw.get_metric_statistics(
            Namespace="AWS/ECS",
            MetricName="RunningTaskCount",
            Dimensions=[
                {"Name":"ClusterName","Value":cluster},
                {"Name":"ServiceName","Value":service}
            ],
            StartTime=start,
            EndTime=end,
            Period=300,
            Statistics=["Average"]
        )
    except (ClientError, BotoCoreError):
        traceback.print_exc()
        raise MetricFetchError("Failed to fetch ECS metrics")

    datapoints = response.get("Datapoints", [])
    if not datapoints:
        raise NoDataError("No ECS metric data found")

    downtime_minutes = sum(5 for d in datapoints if d["Average"] == 0)
    downtime_hours = downtime_minutes / 60

    print("\n========== ECS APPLICATION DOWNTIME REPORT ==========")
    print(f"Cluster      : {cluster}")
    print(f"Service      : {service}")
    print(f"Period       : {start} -> {end}")
    print(f"Downtime     : {downtime_minutes} minutes ({downtime_hours:.2f} hrs)")

    if downtime_minutes == 0:
        print("✅ No ECS application downtime detected")

    return downtime_minutes


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    try:
        REGION = "us-east-1"

        # Date range (1 month)
        END_DATE = datetime.utcnow()
        START_DATE = END_DATE - timedelta(days=30)

        # -------- EC2 CONFIG --------
        EC2_INSTANCE_ID = "i-xxxxxxxxxxxx"

        # -------- ECS CONFIG --------
        ECS_CLUSTER = "prod-cluster"
        ECS_SERVICE = "orders-service"

        ec2_down = get_ec2_app_downtime(EC2_INSTANCE_ID, REGION, START_DATE, END_DATE)
        ecs_down = get_ecs_app_downtime(ECS_CLUSTER, ECS_SERVICE, REGION, START_DATE, END_DATE)

        # DORA RELIABILITY %
        total_seconds = (END_DATE - START_DATE).total_seconds()
        total_downtime_seconds = (ec2_down + ecs_down) * 60

        reliability = (total_seconds - total_downtime_seconds) / total_seconds * 100
        print("\n========== DORA RELIABILITY KPI ==========")
        print(f"Reliability % = {reliability:.5f}")

    except Exception as e:
        print("\n❌ SCRIPT FAILED")
        traceback.print_exc()
        raise SystemExit(1)


##############₹₹₹₹₹########₹₹₹₹₹₹₹##₹₹₹₹₹₹₹₹₹₹2########@@@@@@######


ALB

def get_alb_app_downtime(lb_arn, target_group, start, end):
    cw = boto3.client("cloudwatch")

    response = cw.get_metric_statistics(
        Namespace="AWS/ApplicationELB",
        MetricName="UnHealthyHostCount",
        Dimensions=[
            {"Name":"LoadBalancer","Value":lb_arn},
            {"Name":"TargetGroup","Value":target_group}
        ],
        StartTime=start,
        EndTime=end,
        Period=300,
        Statistics=["Average"]
    )

    if not response["Datapoints"]:
        raise Exception("No ALB metrics")

    downtime = sum(5 for d in response["Datapoints"] if d["Average"] > 0)
    return downtime