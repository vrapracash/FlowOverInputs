
config.py

AWS_REGION = "us-east-1"
CLOUDTRAIL_BUCKET = "my-org-cloudtrail-logs"
CLOUDTRAIL_PREFIX = "AWSLogs/123456789012/CloudTrail/"


utils.py

import json, gzip, boto3, traceback
from botocore.exceptions import ClientError

s3 = boto3.client("s3")

ec2_downtime_s3.py

#!/usr/bin/env python3
"""
EC2 Downtime Analyzer from CloudTrail S3 Logs
"""

import boto3, pandas as pd
from datetime import datetime, timedelta
from utils import read_gzip_json_from_s3
from config import *
import traceback

s3 = boto3.client("s3")

# ---------------- MAIN ---------------- #

def list_cloudtrail_files(start, end):
    keys = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=CLOUDTRAIL_BUCKET, Prefix=CLOUDTRAIL_PREFIX):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def parse_ec2_state_events(instance_id, start, end):
    files = list_cloudtrail_files(start, end)
    events = []

    for key in files:
        if not key.endswith(".gz"):
            continue

        data = read_gzip_json_from_s3(CLOUDTRAIL_BUCKET, key)
        for record in data.get("Records", []):
            if record.get("eventSource") == "ec2.amazonaws.com":
                if record.get("eventName") in ["StartInstances", "StopInstances", "TerminateInstances"]:
                    for res in record.get("resources", []):
                        if res.get("resourceName") == instance_id:
                            events.append({
                                "time": datetime.fromisoformat(record["eventTime"].replace("Z","+00:00")),
                                "event": record["eventName"]
                            })
    return events


def calculate_downtime(events, start, end):
    events.sort(key=lambda x: x["time"])
    downtime = 0
    last_stop = None

    for e in events:
        if e["event"] in ["StopInstances", "TerminateInstances"]:
            last_stop = e["time"]

        elif e["event"] == "StartInstances" and last_stop:
            downtime += (e["time"] - last_stop).total_seconds()
            last_stop = None

    if last_stop:
        downtime += (end - last_stop).total_seconds()

    return downtime


# ---------------- RUN ---------------- #

if __name__ == "__main__":
    try:
        INSTANCE_ID = "i-xxxxxxxxxxxx"

        END = datetime.utcnow()
        START = END - timedelta(days=30)

        events = parse_ec2_state_events(INSTANCE_ID, START, END)
        if not events:
            raise Exception("No CloudTrail EC2 state events found")

        downtime = calculate_downtime(events, START, END)

        print("\n========= EC2 ENTERPRISE DOWNTIME REPORT =========")
        print(f"Instance: {INSTANCE_ID}")
        print(f"Downtime Hours: {downtime/3600:.2f}")
        if downtime == 0:
            print("✅ No downtime observed")

    except Exception:
        print("SCRIPT FAILED")
        traceback.print_exc()
        raise SystemExit(1)

def read_gzip_json_from_s3(bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        with gzip.GzipFile(fileobj=obj["Body"]) as gz:
            return json.loads(gz.read().decode())
    except Exception:
        traceback.print_exc()
        raise Exception(f"Failed to read {key}")

########
#ecs_downtime.py

#!/usr/bin/env python3

import boto3, traceback
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

ecs = boto3.client("ecs")
cw = boto3.client("cloudwatch")

def get_ecs_service_downtime(cluster, service, start, end):

    # CloudWatch metric for running tasks
    data = cw.get_metric_statistics(
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

    if not data["Datapoints"]:
        raise Exception("No ECS metrics found")

    downtime = 0
    for p in data["Datapoints"]:
        if p["Average"] == 0:
            downtime += 5

    print("\n========= ECS DOWNTIME REPORT =========")
    print(f"Cluster: {cluster}")
    print(f"Service: {service}")
    print(f"Downtime Minutes: {downtime}")
    print(f"Downtime Hours: {downtime/60:.2f}")

    if downtime == 0:
        print("✅ No ECS downtime detected")

    return downtime


if __name__ == "__main__":
    try:
        CLUSTER = "prod-cluster"
        SERVICE = "orders-service"

        END = datetime.utcnow()
        START = END - timedelta(days=30)

        get_ecs_service_downtime(CLUSTER, SERVICE, START, END)

    except Exception:
        print("SCRIPT FAILED")
        traceback.print_exc()
        raise SystemExit(1)
