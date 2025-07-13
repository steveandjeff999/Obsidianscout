import requests
import json
import os
from datetime import datetime
from flask import current_app
import uuid
import hashlib

class SyncManager:
    """Manages synchronization of scouting data across devices"""
    
    def __init__(self):
        self.config = self.load_sync_config()
        self.base_url = self.config.get('sync_server', {}).get('base_url', '')
        self.enabled = self.config.get('sync_server', {}).get('enabled', False)
        self.timeout = self.config.get('sync_server', {}).get('timeout', 30)
        self.retry_attempts = self.config.get('sync_server', {}).get('retry_attempts', 3)
        
    def load_sync_config(self):
        """Load sync configuration from JSON file"""
        try:
            config_path = os.path.join(os.getcwd(), 'config', 'sync_config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    return json.load(f)
            else:
                return {"sync_server": {"enabled": False}}
        except Exception as e:
            print(f"Error loading sync configuration: {e}")
            return {"sync_server": {"enabled": False}}
    
    def is_server_available(self):
        """Check if sync server is available"""
        if not self.enabled or not self.base_url:
            return False
            
        try:
            # Try to ping the server
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5,
                headers=self.get_headers()
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def get_headers(self):
        """Get headers for API requests"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Add authentication if configured
        auth_config = self.config.get('sync_server', {}).get('auth', {})
        if auth_config.get('api_key'):
            headers['Authorization'] = f"Bearer {auth_config['api_key']}"
        
        if auth_config.get('team_key'):
            headers['X-Team-Key'] = auth_config['team_key']
        
        return headers
    
    def upload_pit_data(self, pit_data_list):
        """Upload pit scouting data to server"""
        if not self.enabled or not self.base_url:
            raise Exception("Sync server not configured or disabled")
        
        if not self.is_server_available():
            raise Exception("Sync server is not available")
        
        endpoint = self.config.get('sync_server', {}).get('endpoints', {}).get('upload', '/pit-scouting/upload')
        url = f"{self.base_url}{endpoint}"
        
        # Prepare data for upload
        upload_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'device_id': self.get_device_id(),
            'data': [item.to_dict() for item in pit_data_list]
        }
        
        # Add data checksum for integrity
        upload_data['checksum'] = self.calculate_checksum(upload_data['data'])
        
        for attempt in range(self.retry_attempts):
            try:
                response = requests.post(
                    url,
                    json=upload_data,
                    headers=self.get_headers(),
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return {
                        'success': True,
                        'uploaded_count': result.get('uploaded_count', len(pit_data_list)),
                        'server_response': result
                    }
                else:
                    error_msg = f"Server returned status {response.status_code}: {response.text}"
                    if attempt == self.retry_attempts - 1:
                        raise Exception(error_msg)
                    
            except requests.exceptions.ConnectionError:
                if attempt == self.retry_attempts - 1:
                    raise Exception("Unable to connect to sync server")
            except requests.exceptions.Timeout:
                if attempt == self.retry_attempts - 1:
                    raise Exception("Request timed out")
            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    raise Exception(f"Upload failed: {str(e)}")
        
        return {'success': False, 'error': 'Upload failed after all retries'}
    
    def download_pit_data(self, since_timestamp=None, event_id=None):
        """Download pit scouting data from server"""
        if not self.enabled or not self.base_url:
            raise Exception("Sync server not configured or disabled")
        
        if not self.is_server_available():
            raise Exception("Sync server is not available")
        
        endpoint = self.config.get('sync_server', {}).get('endpoints', {}).get('download', '/pit-scouting/download')
        url = f"{self.base_url}{endpoint}"
        
        # Add query parameters
        params = {}
        if since_timestamp:
            params['since'] = since_timestamp
        if event_id:
            params['event_id'] = event_id
        
        for attempt in range(self.retry_attempts):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=self.get_headers(),
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Verify checksum if provided
                    if 'checksum' in result and 'data' in result:
                        calculated_checksum = self.calculate_checksum(result['data'])
                        if calculated_checksum != result['checksum']:
                            raise Exception("Data integrity check failed")
                    
                    return {
                        'success': True,
                        'data': result.get('data', []),
                        'server_timestamp': result.get('timestamp')
                    }
                else:
                    error_msg = f"Server returned status {response.status_code}: {response.text}"
                    if attempt == self.retry_attempts - 1:
                        raise Exception(error_msg)
                    
            except requests.exceptions.ConnectionError:
                if attempt == self.retry_attempts - 1:
                    raise Exception("Unable to connect to sync server")
            except requests.exceptions.Timeout:
                if attempt == self.retry_attempts - 1:
                    raise Exception("Request timed out")
            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    raise Exception(f"Download failed: {str(e)}")
        
        return {'success': False, 'error': 'Download failed after all retries'}
    
    def sync_pit_data(self, local_data_list, event_id=None):
        """Perform bidirectional sync - upload local data and download remote data"""
        results = {
            'upload_success': False,
            'download_success': False,
            'uploaded_count': 0,
            'downloaded_count': 0,
            'new_data': [],
            'errors': []
        }
        
        try:
            # First, upload local unuploaded data
            if local_data_list:
                upload_result = self.upload_pit_data(local_data_list)
                results['upload_success'] = upload_result['success']
                results['uploaded_count'] = upload_result.get('uploaded_count', 0)
                
                if not upload_result['success']:
                    results['errors'].append(f"Upload failed: {upload_result.get('error', 'Unknown error')}")
            
            # Then, download new data from server
            # Use the earliest timestamp from local data as the baseline
            since_timestamp = None
            if local_data_list:
                timestamps = [item.timestamp for item in local_data_list if item.timestamp]
                if timestamps:
                    since_timestamp = min(timestamps).isoformat()
            
            download_result = self.download_pit_data(since_timestamp, event_id)
            results['download_success'] = download_result['success']
            
            if download_result['success']:
                results['new_data'] = download_result.get('data', [])
                results['downloaded_count'] = len(results['new_data'])
            else:
                results['errors'].append(f"Download failed: {download_result.get('error', 'Unknown error')}")
                
        except Exception as e:
            results['errors'].append(f"Sync failed: {str(e)}")
        
        return results
    
    def calculate_checksum(self, data):
        """Calculate MD5 checksum for data integrity"""
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.md5(data_str.encode()).hexdigest()
    
    def get_device_id(self):
        """Get unique device identifier"""
        # Try to get from environment or generate one
        device_id = os.environ.get('DEVICE_ID')
        if not device_id:
            # Generate a unique device ID based on machine characteristics
            import platform
            machine_info = f"{platform.node()}-{platform.machine()}-{platform.system()}"
            device_id = hashlib.md5(machine_info.encode()).hexdigest()[:16]
        
        return device_id
    
    def get_sync_status(self):
        """Get current sync status"""
        return {
            'enabled': self.enabled,
            'server_available': self.is_server_available(),
            'base_url': self.base_url,
            'device_id': self.get_device_id(),
            'last_sync': self.get_last_sync_timestamp()
        }
    
    def get_last_sync_timestamp(self):
        """Get timestamp of last successful sync"""
        try:
            sync_log_path = os.path.join(os.getcwd(), 'instance', 'last_sync.json')
            if os.path.exists(sync_log_path):
                with open(sync_log_path, 'r') as f:
                    sync_data = json.load(f)
                    return sync_data.get('last_sync_timestamp')
        except Exception:
            pass
        return None
    
    def update_last_sync_timestamp(self, timestamp=None):
        """Update the last sync timestamp"""
        if timestamp is None:
            timestamp = datetime.utcnow().isoformat()
        
        try:
            sync_log_path = os.path.join(os.getcwd(), 'instance', 'last_sync.json')
            sync_data = {'last_sync_timestamp': timestamp}
            with open(sync_log_path, 'w') as f:
                json.dump(sync_data, f, indent=2)
        except Exception as e:
            print(f"Error updating sync timestamp: {e}")
