#!/usr/bin/env python3
"""
Diagnostic script to check if jobs are in Redis queue.
"""
import requests
import json
import os

# Get REDIS_URL from environment or use production default
redis_url = os.getenv("REDIS_URL")
if not redis_url:
    print("REDIS_URL not set - checking production endpoint instead")
    # Check production
    try:
        full_response = requests.get(
            "https://web-production-3afc5.up.railway.app/api/v1/arrangements?include_unsaved=true",
            timeout=30
        )
        if full_response.status_code == 200:
            all_arrangements = full_response.json()
            queued = [a for a in all_arrangements if isinstance(a, dict) and a.get('status') == 'queued']
            print(f"\nProduction arrangements summary:")
            print(f"Total: {len(all_arrangements)}")
            print(f"Queued: {len(queued)}")
            if queued:
                print(f"\nFirst 3 queued arrangements (IDs):")
                for arr in queued[:3]:
                    print(f"  - ID {arr.get('id')}: created {arr.get('created_at')}")
        else:
            print(f"Failed to fetch: {full_response.status_code}")
    except Exception as e:
        print(f"Failed to fetch: {e}")
else:
    # Try to connect to Redis locally
    try:
        import redis
        from rq import Queue
        
        conn = redis.from_url(redis_url)
        conn.ping()
        print(f"✅ Connected to Redis at {redis_url}")
        
        # Check render queue
        queue = Queue(name="render", connection=conn)
        print(f"\nRender queue jobs: {len(queue.jobs)}")
        
        if queue.jobs:
            print("\nFirst 3 queued jobs:")
            for job in queue.jobs[:3]:
                print(f"  - {job.id}")
                print(f"    Function: {job.func_name}")
                print(f"    Args: {job.args}")
                print(f"    Created: {job.created_at}")
        
        # Check for failed jobs
        failed = Queue(name="failed", connection=conn)
        print(f"\nFailed queue jobs: {len(failed.jobs)}")
        if failed.jobs:
            print("\nFirst 3 failed jobs:")
            for job in failed.jobs[:3]:
                print(f"  - {job.id}")
                if job.exc_info:
                    print(f"    Error: {job.exc_info[:200]}")
                    
    except Exception as e:
        print(f"❌ Redis diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
