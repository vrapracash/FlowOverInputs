# -*- coding: utf-8 -*-
import boto3
import pandas as pd
import traceback
from datetime import datetime, timedelta, UTC
from botocore.exceptions import ClientError, BotoCoreError

# ---------------- CUSTOM EXCEPTIONS ---------------- #
class AWSInitError(Exception): pass
class MetricFetchError(Exception): pass

def init_clients(region):
    try:
        return boto3.client("cloudwatch", region_name=region)
    except Exception as e:
        raise AWSInitError("Failed to initialize CloudWatch client") from e

def get_ecs_app_downtime(cluster, service, region, start, end):
    cw = init_clients(region)
    all_datapoints = []
    
    # Chunking: 5 days max per request
    delta = timedelta(days=5)
    current_start = start

    print(f"  Checking {service}...")

    while current_start < end:
        current_end = min(current_start + delta, end)
        try:
            response = cw.get_metric_statistics(
                Namespace="ECS/ContainerInsights",  # FIXED: Correct namespace
                MetricName="RunningTaskCount",
                Dimensions=[
                    {"Name": "ClusterName", "Value": cluster},
                    {"Name": "ServiceName", "Value": service}
                ],
                StartTime=current_start,
                EndTime=current_end,
                Period=300,  # 5 minutes
                Statistics=["Average"]
            )
            all_datapoints.extend(response.get("Datapoints", []))
        except ClientError as e:
            print(f"    API Error chunk {current_start}: {e}")
            # Continue to next chunk
        
        current_start = current_end

    print(f"    Found {len(all_datapoints)} datapoints")

    if not all_datapoints:
        # NO DATA = 100% downtime (service never ran)
        total_periods = int((end - start).total_seconds() / 300)
        downtime_minutes = total_periods * 5
        print(f"    ⚠️  NO METRICS = {downtime_minutes} min downtime (service inactive)")
        
        # Create empty DF for consistency
        df = pd.DataFrame({
            "Timestamp": [start],
            "Service": ["ECS"],
            "Resource": [service],
            "MetricValue": [0.0]
        })
        return df, downtime_minutes

    # Process data
    all_datapoints = sorted(all_datapoints, key=lambda x: x["Timestamp"])
    df = pd.DataFrame(all_datapoints)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df["Service"] = "ECS"
    df["Resource"] = service
    df.rename(columns={"Average": "MetricValue"}, inplace=True)

    # Downtime: Average == 0 OR gaps in data = downtime
    downtime_minutes = sum(5 for d in all_datapoints if d["Average"] == 0)
    
    # Account for data gaps (missing datapoints = downtime)
    expected_points = int((end - start).total_seconds() / 300)
    gap_downtime = max(0, expected_points - len(all_datapoints)) * 5
    total_downtime = downtime_minutes + gap_downtime
    
    print(f"    Recorded downtime: {downtime_minutes} min + gaps: {gap_downtime} min")
    
    return df[["Timestamp", "Service", "Resource", "MetricValue"]], total_downtime

if __name__ == "__main__":
    try:
        REGION = "eu-west-1"
        END = datetime.now(UTC)
        START = END - timedelta(days=30)

        ECS_CLUSTER = "analytics-dashboards-prod"  
        ECS_SERVICES = ["accredify_v0-prod", "audit_v2_backend-prod", "cbs_dashboard_backend-prod",
                         "client_dashboard_api-prod", "moheri-oman-dashboard-backend-prod"] # List of services

        # ECS_CLUSTER = "moheri-oman"
        # ECS_SERVICES = ["moheri-oman-frontend-prod", "moheri-oman-frontend-prod"] # List of services

        # ECS_CLUSTER = "PaymentDashboard-Prod"
        # ECS_SERVICES = ["paymentdashboard-backend-prod", "paymentdashboard-frontend-prod"] # List of services

        print(f"Checking ECS cluster '{ECS_CLUSTER}' from {START} to {END}")
        print(f"Services: {ECS_SERVICES}")

        all_reports = []

        for service in ECS_SERVICES:
            ecs_df, ecs_down = get_ecs_app_downtime(ECS_CLUSTER, service, REGION, START, END)

            # Save CSV
            output_file = f"cloudwatch_downtime_metrics_{service}.csv"
            ecs_df.sort_values("Timestamp").to_csv(output_file, index=False)

            # Summary
            total_time_minutes = (END - START).total_seconds() / 60
            uptime_pct = ((total_time_minutes - ecs_down) / total_time_minutes) * 100 if total_time_minutes > 0 else 0

            print(f"\n✅ {service}:")
            print(f"   Downtime: {ecs_down:.0f} minutes ({ecs_down/total_time_minutes*100:.1f}%)")
            print(f"   Uptime:   {uptime_pct:.1f}%")
            print(f"   Saved:    {output_file}")

            all_reports.append({"Service": service, "Downtime_Min": ecs_down, "Uptime_Pct": uptime_pct})

        # Summary table
        summary_df = pd.DataFrame(all_reports)
        print(f"\n📊 SUMMARY TABLE:")
        print(summary_df.to_string(index=False))

    except Exception as e:
        print("\n❌ SCRIPT FAILED")
        traceback.print_exc()
        raise SystemExit(1)
