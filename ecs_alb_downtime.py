# ecs_alb_downtime_report.py

import boto3
import pandas as pd
from datetime import datetime, timedelta, UTC, date
import traceback

REGION = "eu-west-1"
CLUSTER_NAME = "analytics-dashboards-prod"
DAYS = 30
DATE = date.today()

STATUS_FILE = f"ecs_downtime_status_{DATE}.txt"
OUTPUT_FILE = f"ecs_alb_downtime_report_{DATE}.xlsx"


def log(msg):
    print(msg)
    with open(STATUS_FILE, "a", encoding='utf-8') as f:
        f.write(msg + "\n")


# ---------- AWS CLIENTS ----------
ecs = boto3.client("ecs", region_name=REGION)
elbv2 = boto3.client("elbv2", region_name=REGION)
cw = boto3.client("cloudwatch", region_name=REGION)


# ---------- GET ECS SERVICES ----------
def get_services(cluster):
    services = []
    paginator = ecs.get_paginator("list_services")
    for page in paginator.paginate(cluster=cluster):
        services.extend(page["serviceArns"])
    return services


# ---------- GET TARGET GROUP ----------
def get_target_group_and_lb(service_arn):
    svc = ecs.describe_services(cluster=CLUSTER_NAME, services=[service_arn])["services"][0]
    
    if "loadBalancers" not in svc or not svc["loadBalancers"]:
        return None, None
    
    tg_arn = svc["loadBalancers"][0]["targetGroupArn"]

    #Find LoadBalancer for TargetGroup
    tg_info = elbv2.describe_target_groups(TargetGroupArns=[tg_arn])["TargetGroups"][0]
    lb_arn = tg_info["LoadBalancerArns"][0]

    lb_name = lb_arn.split("loadbalancer/")[1]
    return tg_arn.split(":")[-1], lb_name


# ---------- GET ALB HEALTH METRICS ----------
def get_downtime(tg_name, lb_name, start, end):
    all_points = []
    delta = timedelta(days=1)
    current = start

    while current < end:
        chunk_end = min(current + delta, end)

        response = cw.get_metric_statistics(
            Namespace="AWS/ApplicationELB",
            MetricName="HealthyHostCount",
            Dimensions=[
                {"Name": "TargetGroup", "Value": tg_name},
                {"Name": "LoadBalancer", "Value": lb_name}
            ],
            StartTime=start,
            EndTime=end,
            Period=60,
            Statistics=["Average"]
        )

        all_points.extend(response.get("Datapoints", []))
        current = chunk_end

    all_points = sorted(all_points, key=lambda x: x["Timestamp"])
    # points = sorted(response.get("Datapoints", []), key=lambda x: x["Timestamp"])

    if not all_points:
        return None, (end - start).total_seconds() / 60

    df = pd.DataFrame(all_points)
    df["Timestamp"] = df["Timestamp"].dt.tz_localize(None)#pd.to_datetime(df["Timestamp"])
    df.rename(columns={"Average": "HealthyHosts"}, inplace=True)

    downtime = sum(1 for p in all_points if p["Average"] == 0)
    return df, downtime




# ---------- MAIN ----------
def main():
    log(f"=== ECS ALB DOWNTIME REPORT STARTED {datetime.now(UTC)} ===")

    end = datetime.now(UTC)
    start = end - timedelta(days=DAYS)

    services = get_services(CLUSTER_NAME)
    log(f"Found {len(services)} services in cluster {CLUSTER_NAME}")

    writer = pd.ExcelWriter(OUTPUT_FILE, engine="xlsxwriter")
    summary = []

    for svc_arn in services:
        svc_name = svc_arn.split("/")[-1]
        log(f"Processing service: {svc_name}")

        tg_name, lb_name = get_target_group_and_lb(svc_arn)

        if not tg_name:
            log(f"  ⚠ No ALB target group for {svc_name}, skipping")
            continue

        df, downtime = get_downtime(tg_name, lb_name, start, end)

        total_minutes = (end - start).total_seconds() / 60
        uptime = 100 - (downtime / total_minutes * 100)

        summary.append({
            "Service": svc_name,
            "Downtime_Minutes": downtime,
            "Uptime_%": round(uptime, 2)
        })

        if df is not None:
            df.to_excel(writer, sheet_name=svc_name[:31], index=False)

        log(f"  ✅ Downtime: {downtime:.0f} min | Uptime: {uptime:.2f}%")

    # Write summary sheet
    summary_df = pd.DataFrame(summary)
    summary_df.to_excel(writer, sheet_name="SUMMARY", index=False)
    writer.close()

    log(f"Report saved: {OUTPUT_FILE}")
    log("=== FINISHED ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("❌ SCRIPT FAILED")
        log(traceback.format_exc())
