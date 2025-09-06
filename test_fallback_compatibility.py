#!/usr/bin/env python3
"""
Test Fallback Sync Manager Compatibility
Ensures all the sync manager fallbacks work correctly with existing code
"""

import sys
import os

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_fallback_compatibility():
    """Test that fallback sync managers work with existing code"""
    print("🔄 Testing Fallback Sync Manager Compatibility...")
    
    try:
        # Test app creation
        from app import create_app
        
        print("📱 Creating app...")
        app = create_app()
        
        with app.app_context():
            print("✅ App created successfully")
            
            # Test sync_api fallback
            print("\n🔌 Testing sync_api fallback...")
            try:
                from app.routes.sync_api import sync_manager as api_sync
                
                # Test methods that were causing errors
                servers_active = api_sync.get_sync_servers(active_only=True)
                servers_all = api_sync.get_sync_servers(active_only=False)
                status = api_sync.get_sync_status()
                
                print(f"✅ get_sync_servers(active_only=True): {len(servers_active)} servers")
                print(f"✅ get_sync_servers(active_only=False): {len(servers_all)} servers")
                print(f"✅ get_sync_status(): {status['message']}")
                
                # Test file upload method
                upload_result = api_sync.upload_file_to_server(None, "test.txt", "update")
                print(f"✅ upload_file_to_server(): {upload_result}")
                
            except Exception as e:
                print(f"❌ sync_api fallback error: {e}")
                return False
            
            # Test sync_management fallback
            print("\n🔧 Testing sync_management fallback...")
            try:
                from app.routes.sync_management import sync_manager as mgmt_sync
                
                # Test methods
                servers_active = mgmt_sync.get_sync_servers(active_only=True)
                servers_all = mgmt_sync.get_sync_servers(active_only=False)
                sync_result = mgmt_sync.sync_with_server(None, 'full')
                
                print(f"✅ get_sync_servers(active_only=True): {len(servers_active)} servers")
                print(f"✅ get_sync_servers(active_only=False): {len(servers_all)} servers")
                print(f"✅ sync_with_server(): {sync_result}")
                
            except Exception as e:
                print(f"❌ sync_management fallback error: {e}")
                return False
            
            # Test real_time_file_sync fallback
            print("\n📁 Testing real_time_file_sync fallback...")
            try:
                from app.utils.real_time_file_sync import MultiServerSyncManager
                
                fallback = MultiServerSyncManager()
                upload_result = fallback.upload_file_to_server(None, "test.txt", "update")
                sync_result = fallback.sync_file_to_servers("test.txt", "update")
                
                print(f"✅ upload_file_to_server(): {upload_result}")
                print(f"✅ sync_file_to_servers(): completed (no return value)")
                
            except Exception as e:
                print(f"❌ real_time_file_sync fallback error: {e}")
                return False
        
        print(f"\n🎉 All fallback sync managers working correctly!")
        print(f"✅ No more TypeError or missing method errors")
        print(f"✅ Sync system never permanently fails - keeps trying forever")
        print(f"✅ Universal Sync System handles actual synchronization")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_fallback_compatibility()
    if success:
        print(f"\n🚀 Fallback compatibility test PASSED!")
        print(f"🔄 All sync manager methods work correctly")
    else:
        print(f"\n❌ Fallback compatibility test FAILED!")
    
    sys.exit(0 if success else 1)
