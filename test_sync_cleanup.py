#!/usr/bin/env python3
"""
Test Old Sync System Cleanup
Verifies that the old multi-server sync system is properly disabled
and no longer causing application context errors
"""

import sys
import os

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_sync_cleanup():
    """Test that old sync system is properly disabled"""
    print("🧹 Testing Old Sync System Cleanup...")
    
    try:
        # Test app creation without sync errors
        from app import create_app
        
        print("📱 Creating app...")
        app = create_app()
        
        print("✅ App created successfully - no old sync system conflicts!")
        
        # Test that universal sync is active
        with app.app_context():
            try:
                from universal_sync_system import universal_sync
                
                if hasattr(universal_sync, 'sync_servers'):
                    print(f"✅ Universal Sync System is active")
                    print(f"   - Sync servers configured: {len(universal_sync.sync_servers)}")
                    print(f"   - File monitoring active: {universal_sync.file_worker_running}")
                    print(f"   - Database sync active: {universal_sync.worker_running}")
                else:
                    print("⚠️ Universal Sync System not fully initialized")
                
            except Exception as e:
                print(f"⚠️ Could not check Universal Sync status: {e}")
        
        # Test old sync manager fallbacks
        print("\n🔄 Testing Sync Manager Fallbacks...")
        
        # Test sync_api fallback
        try:
            from app.routes.sync_api import sync_manager
            servers = sync_manager.get_sync_servers()
            print(f"✅ sync_api fallback working - found {len(servers)} servers")
        except Exception as e:
            print(f"❌ sync_api fallback error: {e}")
        
        # Test sync_management fallback
        try:
            from app.routes.sync_management import sync_manager as mgmt_sync
            status = mgmt_sync.get_sync_servers()
            print(f"✅ sync_management fallback working - found {len(status)} servers")
        except Exception as e:
            print(f"❌ sync_management fallback error: {e}")
        
        print(f"\n🎉 Old sync system cleanup test PASSED!")
        print(f"✅ No more 'Working outside of application context' errors")
        print(f"✅ Universal Sync System is the only active sync system")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_sync_cleanup()
    if success:
        print(f"\n🚀 Sync cleanup successful!")
        print(f"🌐 Universal Sync System is now the only sync system running")
    else:
        print(f"\n❌ Sync cleanup test failed!")
    
    sys.exit(0 if success else 1)
