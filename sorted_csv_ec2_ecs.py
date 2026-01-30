#!/usr/bin/env python3
"""
Enterprise CloudWatch Downtime Analyzer
EC2 + ECS with Sorted Datapoints + CSV Export
"""

import boto3
import pandas as pd
import traceback
from datetime import datetime, timedelta
from botocore.exceptions import ClientError, BotoCoreError

# ================= EXCEPTIONS ================= #

class MetricFetchError(Exception): pass
class NoDataError(Exception): pass


# ================= INIT ================= #

def init_cw(region):
    try:
        return boto3.client("cloudwatch", region_name=region)
    except Exception:
        traceback.print_exc()
        raise Exception("CloudWatch init failed")


# =====================================================
# EC2 METRICS
# =====================================================

def get_ec2_metrics(instance_id, region, start, end):
    cw = init_cw(region)

    try:
        response = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="StatusCheckFailed",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=end,
            Period=300,
            Statistics=["Sum"]
        )
    except (ClientError, BotoCoreError):
        traceback.print_exc()
        raise MetricFetchError("Failed to fetch EC2 metrics")

    datapoints = response.get("Datapoints", [])
    if not datapoints:
        raise NoDataError("No EC2 metrics found")

    # Sort by timestamp
    datapoints = sorted(datapoints, key=lambda x: x["Timestamp"])

    # Convert to DataFrame
    df = pd.DataFrame(datapoints)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df["Service"] = "EC2"
    df["Resource"] = instance_id
    df.rename(columns={"Sum": "MetricValue"}, inplace=True)

    # Calculate downtime
    downtime_minutes = sum(5 for d in datapoints if d["Sum"] > 0)

    return df[["Timestamp", "Service", "Resource", "MetricValue"]], downtime_minutes


# =====================================================
# ECS METRICS
# =====================================================

def get_ecs_metrics(cluster, service, region, start, end):
    cw = init_cw(region)

    try:
        response = cw.get_metric_statistics(
            Namespace="AWS/ECS",
            MetricName="RunningTaskCount",
            Dimensions=[
                {"Name": "ClusterName", "Value": cluster},
                {"Name": "ServiceName", "Value": service}
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
        raise NoDataError("No ECS metrics found")

    # Sort by timestamp
    datapoints = sorted(datapoints, key=lambda x: x["Timestamp"])

    # Convert to DataFrame
    df = pd.DataFrame(datapoints)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df["Service"] = "ECS"
    df["Resource"] = f"{cluster}/{service}"
    df.rename(columns={"Average": "MetricValue"}, inplace=True)

    # Downtime = RunningTaskCount == 0
    downtime_minutes = sum(5 for d in datapoints if d["Average"] == 0)

    return df[["Timestamp", "Service", "Resource", "MetricValue"]], downtime_minutes


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    try:
        REGION = "us-east-1"

        # Time range (last 30 days)
        END = datetime.utcnow()
        START = END - timedelta(days=30)

        # CONFIG
        EC2_INSTANCE_ID = "i-xxxxxxxxxxxx"
        ECS_CLUSTER = "prod-cluster"
        ECS_SERVICE = "orders-service"

        # Fetch data
        ec2_df, ec2_down = get_ec2_metrics(EC2_INSTANCE_ID, REGION, START, END)
        ecs_df, ecs_down = get_ecs_metrics(ECS_CLUSTER, ECS_SERVICE, REGION, START, END)

        # Combine EC2 + ECS
        final_df = pd.concat([ec2_df, ecs_df]).sort_values("Timestamp")

        # Save CSV
        output_file = "cloudwatch_downtime_metrics.csv"
        final_df.to_csv(output_file, index=False)

        # Print Summary
        print("\n================ DOWNTIME SUMMARY ================")
        print(f"EC2 Downtime Minutes: {ec2_down}")
        print(f"ECS Downtime Minutes: {ecs_down}")

        total_downtime_seconds = (ec2_down + ecs_down) * 60
        total_time_seconds = (END - START).total_seconds()

        reliability = (total_time_seconds - total_downtime_seconds) / total_time_seconds * 100

        print(f"Total Downtime (seconds): {total_downtime_seconds}")
        print(f"DORA Reliability %: {reliability:.6f}")
        print(f"CSV Saved: {output_file}")

        if ec2_down == 0 and ecs_down == 0:
            print("✅ No downtime observed in this period")

    except Exception as e:
        print("\n❌ SCRIPT FAILED")
        traceback.print_exc()
        raise SystemExit(1)