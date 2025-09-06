#!/usr/bin/env python3
"""
Test Enhanced Fallback Sync Manager
Verifies all methods needed by sync management UI work correctly
"""

import sys
import os

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_sync_manager_methods():
    """Test all sync manager methods work correctly"""
    print("🔧 Testing Enhanced Fallback Sync Manager...")
    
    try:
        from app import create_app
        
        app = create_app()
        
        with app.app_context():
            from app.routes.sync_management import sync_manager
            
            print("✅ Testing sync manager methods...")
            
            # Test all the methods that were causing errors
            methods_to_test = [
                ('get_sync_servers', lambda: sync_manager.get_sync_servers()),
                ('get_sync_servers with active_only=False', lambda: sync_manager.get_sync_servers(active_only=False)),
                ('get_sync_status', lambda: sync_manager.get_sync_status()),
                ('sync_all_servers', lambda: sync_manager.sync_all_servers()),
                ('force_full_sync', lambda: sync_manager.force_full_sync()),
                ('ping_server', lambda: sync_manager.ping_server(None))
            ]
            
            results = {}
            
            for method_name, method_call in methods_to_test:
                try:
                    result = method_call()
                    results[method_name] = "✅ Working"
                    print(f"   ✅ {method_name}: OK")
                except Exception as e:
                    results[method_name] = f"❌ Error: {e}"
                    print(f"   ❌ {method_name}: Error - {e}")
            
            # Test properties
            print("\n✅ Testing sync manager properties...")
            try:
                # Test reading properties
                print(f"   📊 sync_enabled: {sync_manager.sync_enabled}")
                print(f"   📊 sync_interval: {sync_manager.sync_interval}")
                print(f"   📊 file_watch_interval: {sync_manager.file_watch_interval}")
                print(f"   📊 server_id: {sync_manager.server_id}")
                
                # Test setting properties
                sync_manager.sync_enabled = False
                sync_manager.sync_interval = 60
                sync_manager.file_watch_interval = 10
                
                print(f"   ✅ Properties can be set and read")
                results['properties'] = "✅ Working"
                
            except Exception as e:
                print(f"   ❌ Property error: {e}")
                results['properties'] = f"❌ Error: {e}"
            
            # Summary
            print(f"\n📊 Test Results:")
            working_count = sum(1 for v in results.values() if v.startswith("✅"))
            total_count = len(results)
            
            for name, result in results.items():
                print(f"   {result} {name}")
            
            print(f"\n🎯 Summary: {working_count}/{total_count} methods working")
            
            if working_count == total_count:
                print(f"🎉 All sync manager methods working correctly!")
                print(f"✅ No more AttributeError or TypeError issues")
                return True
            else:
                print(f"❌ Some methods still have issues")
                return False
                
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_sync_manager_methods()
    if success:
        print(f"\n🚀 Enhanced Fallback Sync Manager test PASSED!")
        print(f"💪 Sync management UI should work without errors")
    else:
        print(f"\n❌ Enhanced Fallback Sync Manager test FAILED!")
    
    sys.exit(0 if success else 1)
