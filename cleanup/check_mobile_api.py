"""
Quick check if mobile API is accessible
Run this with: python check_mobile_api.py
"""
import urllib.request
import json
import ssl

def check_api():
    """Simple API check without external dependencies"""
    
    url = "https://localhost:8080/api/mobile/health"
    
    print(f"Testing: {url}")
    print("="*60)
    
    try:
        # Create SSL context that doesn't verify self-signed certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        response = urllib.request.urlopen(url, timeout=5, context=ssl_context)
        data = response.read().decode('utf-8')
        result = json.loads(data)
        
        print("SUCCESS!")
        print(json.dumps(result, indent=2))
        print("\nMobile API is working!")
        return True
        
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        print(f"\nThe route exists but returned an error.")
        return False
        
    except urllib.error.URLError as e:
        print(f"Connection Error: {e.reason}")
        print(f"\nMake sure the server is running with: python run.py")
        return False
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return False

if __name__ == "__main__":
    print(" Checking Mobile API...")
    print()
    
    if check_api():
        print("\n Next: Try the full test with:")
        print("   pip install requests")
        print("   python test_mobile_api.py")
    else:
        print("\n Troubleshooting:")
        print("   1. Make sure server is running: python run.py")
        print("   2. Check server logs for errors")
        print("   3. Verify the server started successfully")
