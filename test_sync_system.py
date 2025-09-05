#!/usr/bin/env python3
"""
Test script for the sync and locking system
Tests the restored sync functionality after remote update
"""

import os
import sys
import time
import requests
import json
from pathlib import Path

# Add the project root to the path so we can import our modules
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def test_sync_endpoints():
    """Test the sync endpoints to verify functionality"""
    base_url = "http://localhost:5000"  # Adjust if needed
    
    print("🔍 Testing sync system functionality...")
    
    endpoints_to_test = [
        ("/api/sync/status", "GET", "Sync status"),
        ("/api/sync/health", "GET", "Health check"),
        ("/api/sync/ping", "GET", "Ping test"),
        ("/api/sync/locks", "GET", "List locks"),
    ]
    
    results = {}
    
    for endpoint, method, description in endpoints_to_test:
        try:
            print(f"Testing {description}: {method} {endpoint}")
            
            if method == "GET":
                response = requests.get(f"{base_url}{endpoint}", timeout=10)
            else:
                response = requests.request(method, f"{base_url}{endpoint}", timeout=10)
            
            results[endpoint] = {
                "status_code": response.status_code,
                "success": response.status_code in [200, 201, 202],
                "description": description,
                "response": response.text[:200] if response.text else "No response body"
            }
            
            if results[endpoint]["success"]:
                print(f"✅ {description}: SUCCESS")
            else:
                print(f"❌ {description}: FAILED (Status: {response.status_code})")
                
        except requests.exceptions.ConnectionError:
            print(f"❌ {description}: Server not running")
            results[endpoint] = {
                "status_code": None,
                "success": False,
                "description": description,
                "response": "Connection refused - server not running"
            }
        except Exception as e:
            print(f"❌ {description}: ERROR - {e}")
            results[endpoint] = {
                "status_code": None,
                "success": False,
                "description": description,
                "response": f"Exception: {e}"
            }
    
    return results


def test_sync_utils():
    """Test the sync utilities directly"""
    print("\n🔧 Testing sync utilities...")
    
    try:
        from app.utils.sync_utils import SyncLockManager, acquire_lock, release_lock
        print("✅ Successfully imported sync utilities")
        
        # Test lock manager
        lock_manager = SyncLockManager()
        print("✅ Created SyncLockManager instance")
        
        # Test basic lock operations
        test_resource = "test_resource_sync_test"
        server_id = "test_server_123"
        
        print(f"Testing lock acquisition for resource: {test_resource}")
        lock_acquired = lock_manager.acquire_lock(test_resource, server_id)
        
        if lock_acquired:
            print("✅ Lock acquired successfully")
            
            # Test lock release
            released = lock_manager.release_lock(test_resource, server_id)
            if released:
                print("✅ Lock released successfully")
            else:
                print("❌ Failed to release lock")
        else:
            print("❌ Failed to acquire lock")
            
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import sync utilities: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing sync utilities: {e}")
        return False


def main():
    """Run sync system tests"""
    print("=" * 60)
    print("🧪 SYNC SYSTEM TEST SUITE")
    print("=" * 60)
    
    # Test sync utilities
    utils_ok = test_sync_utils()
    
    # Test endpoints if server is running
    print("\n" + "=" * 60)
    endpoint_results = test_sync_endpoints()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    print(f"Sync utilities: {'✅ PASS' if utils_ok else '❌ FAIL'}")
    
    successful_endpoints = sum(1 for result in endpoint_results.values() if result["success"])
    total_endpoints = len(endpoint_results)
    
    print(f"Endpoint tests: {successful_endpoints}/{total_endpoints} passed")
    
    for endpoint, result in endpoint_results.items():
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        print(f"  {endpoint}: {status}")
    
    overall_success = utils_ok and successful_endpoints == total_endpoints
    print(f"\nOverall result: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
    
    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())
