# Copyright (c) Ben Hughes. SPDX-License-Identifier: AGPL-3.0-or-later

import os
import time
import docker
import traceback
from uptime_kuma_api import UptimeKumaApi, MonitorType
from dotenv import load_dotenv

load_dotenv()

KUMA_URL = os.getenv("KUMA_URL", "http://uptime-kuma:3001")
KUMA_USER = os.getenv("KUMA_USER")
KUMA_PASS = os.getenv("KUMA_PASS")
KUMA_TIMEOUT = float(os.getenv("KUMA_TIMEOUT", "30"))
DOCKER_HOST_NAME = os.getenv("DOCKER_HOST_NAME")
NOTIFICATION_NAME = os.getenv("NOTIFICATION_NAME")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "300"))

# Monitor Group name (defaults to host name)
KUMA_GROUP_NAME = os.getenv("KUMA_GROUP_NAME", DOCKER_HOST_NAME)

def get_kuma_host_id(api, name):
    hosts = api.get_docker_hosts()
    for host in hosts:
        if host['name'] == name:
            return host['id']
    return None

def get_notification_id(api, name):
    notifications = api.get_notifications()
    for n in notifications:
        if n['name'] == name:
            return int(n['id'])
    return None

def sync():
    print("--- Starting sync ---")
    try:
        # Connect to Docker
        print("Connecting to Docker socket...")
        client = docker.from_env()
        containers = client.containers.list(all=True)
        container_names = [c.name for c in containers]
        print(f"Found {len(container_names)} containers on host.")

        # Connect to Uptime Kuma
        print(f"Connecting to Uptime Kuma at {KUMA_URL} with timeout {KUMA_TIMEOUT}...")
        with UptimeKumaApi(KUMA_URL, timeout=KUMA_TIMEOUT) as api:
            print(f"Logging in as {KUMA_USER}...")
            api.login(KUMA_USER, KUMA_PASS)
            
            # Get Docker Host ID
            print(f"Looking for Docker Host: {DOCKER_HOST_NAME}...")
            host_id = get_kuma_host_id(api, DOCKER_HOST_NAME)
            if not host_id:
                print(f"CRITICAL: Docker host '{DOCKER_HOST_NAME}' not found.")
                return

            # Get Notification ID (optional)
            notification_list = {}
            if NOTIFICATION_NAME:
                print(f"Looking for Notification: {NOTIFICATION_NAME}...")
                notification_id = get_notification_id(api, NOTIFICATION_NAME)
                if notification_id:
                    print(f"Found notification ID: {notification_id}")
                    notification_list[notification_id] = True
                else:
                    print(f"WARN: Notification '{NOTIFICATION_NAME}' not found. Monitors will be created without notifications.")
            else:
                print("No NOTIFICATION_NAME provided; monitors will be created without notifications.")

            # Get existing monitors
            print("Fetching existing monitors...")
            monitors = api.get_monitors()
            existing_monitor_names = [m['name'] for m in monitors]
            monitor_id_by_name = {m['name']: m['id'] for m in monitors}
            monitor_by_name = {m['name']: m for m in monitors}
            print(f"Found {len(existing_monitor_names)} existing monitors.")

            # Ensure a Monitor Group exists (type GROUP) named after the host
            print(f"Ensuring monitor group exists: '{KUMA_GROUP_NAME}'...")
            group_id = None
            for m in monitors:
                if m.get('name') == KUMA_GROUP_NAME and str(m.get('type')) in ("group", str(MonitorType.GROUP)):
                    group_id = m.get('id')
                    break
            if not group_id:
                try:
                    group_payload = {
                        "type": MonitorType.GROUP,
                        "name": KUMA_GROUP_NAME,
                        "interval": 60,
                        "retryInterval": 60,
                        "resendInterval": 0,
                        "maxretries": 0,
                        "upsideDown": False,
                        "conditions": [],
                        "accepted_statuscodes": ["200-299"],
                        "notificationIDList": notification_list,
                    }
                    res = api._call("add", group_payload)
                    group_id = res.get('monitorID') or res.get('id')
                    print(f"Created group '{KUMA_GROUP_NAME}' with id {group_id}")
                except Exception as e:
                    print(f"CRITICAL: Failed to create monitor group '{KUMA_GROUP_NAME}': {e}")
                    return

            for name in container_names:
                # Basic sync: if monitor with container name doesn't exist, create it
                if name not in existing_monitor_names:
                    print(f"Creating NEW monitor for container: {name}")
                    # Uptime Kuma v2.x requires specific fields to avoid validation errors.
                    try:
                        payload = {
                            "type": MonitorType.DOCKER,
                            "name": name,
                            "docker_container": name,
                            "docker_host": host_id,
                            "parent": int(group_id) if group_id else None,
                            "interval": 60,
                            "retryInterval": 60,
                            "resendInterval": 0,
                            "maxretries": 0,
                            "upsideDown": False,
                            "conditions": [],
                            "accepted_statuscodes": ["200-299"],
                            "notificationIDList": notification_list or {},
                        }
                        res = api._call("add", payload)
                        print(f"Created monitor '{name}' with parent group '{KUMA_GROUP_NAME}'")
                    except Exception as e:
                        print(f"ERROR: Failed to create monitor '{name}': {e}")
                else:
                    # Ensure existing monitor is assigned to the group as parent
                    try:
                        mid = monitor_id_by_name.get(name)
                        m = monitor_by_name.get(name)
                        if mid and m and (m.get('parent') != group_id):
                            api.edit_monitor(int(mid), parent=int(group_id))
                            print(f"Moved existing monitor '{name}' under group '{KUMA_GROUP_NAME}'")
                    except Exception as e:
                        print(f"WARN: Could not set parent for '{name}': {e}")

            print("Sync completed successfully.")
            try:
                with open("/tmp/last_sync.ok", "w") as f:
                    f.write(str(int(time.time())))
            except Exception:
                pass

    except Exception as e:
        print("!!! Error during sync !!!")
        traceback.print_exc()

if __name__ == "__main__":
    print("Kuma Container Sync starting up...")
    print(f"KUMA_URL: {KUMA_URL}")
    print(f"KUMA_USER: {KUMA_USER}")
    
    if not KUMA_USER or not KUMA_PASS:
        print("CRITICAL Error: KUMA_USER and KUMA_PASS must be set.")
        exit(1)
    if not DOCKER_HOST_NAME:
        print("CRITICAL Error: DOCKER_HOST_NAME must be set.")
        exit(1)
    # Default KUMA_GROUP_NAME to DOCKER_HOST_NAME if not provided
    if not KUMA_GROUP_NAME:
        KUMA_GROUP_NAME = DOCKER_HOST_NAME
        print(f"KUMA_GROUP_NAME not set; defaulting to DOCKER_HOST_NAME: {KUMA_GROUP_NAME}")
        
    while True:
        try:
            sync()
        except Exception as e:
            print(f"Unhandled error in main loop: {e}")
            
        print(f"Waiting {SYNC_INTERVAL} seconds for next sync...")
        time.sleep(SYNC_INTERVAL)
