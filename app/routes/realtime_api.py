"""
Real-time Replication API Routes
Receives and applies database operations in real-time from other servers
"""

import logging
from datetime import datetime, timezone
from typing import Dict
from flask import Blueprint, request, jsonify, current_app
from app import db
from app.models import User, ScoutingData, Match, Team, Event
from app.utils.real_time_replication import DisableReplication
from app.utils.simplified_sync import parse_datetime_string, is_datetime_field

logger = logging.getLogger(__name__)

realtime_api = Blueprint('realtime_api', __name__, url_prefix='/api/realtime')

@realtime_api.route('/receive', methods=['POST'])
def receive_operation():
    """Receive and apply a real-time database operation from another server"""
    try:
        data = request.get_json()
        
        if not data or 'operation' not in data:
            return jsonify({'error': 'operation data is required'}), 400
        
        operation = data['operation']
        source_server_id = data.get('source_server_id', 'unknown')
        
        operation_type = operation.get('type')
        table_name = operation.get('table')
        record_data = operation.get('data', {})
        record_id = operation.get('record_id')
        
        logger.debug(f"📥 Received {operation_type} operation for {table_name} from {source_server_id}")
        
        # Model mapping - handle both singular and plural forms
        model_map = {
            'users': User,
            'user': User,
            'scouting_data': ScoutingData,
            'matches': Match,
            'match': Match,
            'teams': Team,
            'team': Team,
            'events': Event,
            'event': Event  # Handle default singular table name
        }
        
        if table_name not in model_map:
            return jsonify({'error': f'Unknown table: {table_name}'}), 400
        
        model_class = model_map[table_name]
        
        # Apply the operation with replication disabled to prevent loops
        with DisableReplication():
            result = apply_operation(model_class, operation_type, record_data, record_id)
        
        if result['success']:
            logger.debug(f"✅ Applied {operation_type} operation for {table_name}:{record_id}")
            return jsonify({
                'success': True,
                'operation_type': operation_type,
                'table': table_name,
                'record_id': record_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        else:
            logger.error(f"❌ Failed to apply {operation_type} operation: {result['error']}")
            return jsonify({'error': result['error']}), 500
            
    except Exception as e:
        logger.error(f"❌ Error processing real-time operation: {e}")
        return jsonify({'error': str(e)}), 500

def apply_operation(model_class, operation_type: str, record_data: Dict, record_id: str):
    """Apply a database operation"""
    try:
        if operation_type == 'insert':
            return apply_insert(model_class, record_data)
        elif operation_type == 'update':
            return apply_update(model_class, record_data, record_id)
        elif operation_type == 'delete':
            return apply_delete(model_class, record_id)
        else:
            return {'success': False, 'error': f'Unknown operation type: {operation_type}'}
            
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}

def apply_insert(model_class, record_data: Dict):
    """Apply an insert operation"""
    try:
        # Check if record already exists
        existing_record = model_class.query.get(record_data.get('id'))
        if existing_record:
            # If it exists, treat as update
            return apply_update(model_class, record_data, record_data.get('id'))
        
        # Process datetime fields
        processed_data = process_datetime_fields(record_data)
        
        # Create new record
        new_record = model_class(**processed_data)
        db.session.add(new_record)
        db.session.commit()
        
        return {'success': True, 'action': 'inserted'}
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Error in apply_insert: {e}")
        return {'success': False, 'error': str(e)}

def apply_update(model_class, record_data: Dict, record_id: str):
    """Apply an update operation"""
    try:
        record = model_class.query.get(record_id)
        if not record:
            # If record doesn't exist, treat as insert
            return apply_insert(model_class, record_data)
        
        # Update record fields
        for key, value in record_data.items():
            if key != 'id' and hasattr(record, key):
                # Process datetime fields
                if is_datetime_field(key):
                    value = parse_datetime_string(value, key)
                setattr(record, key, value)
        
        db.session.commit()
        return {'success': True, 'action': 'updated'}
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Error in apply_update: {e}")
        return {'success': False, 'error': str(e)}

def apply_delete(model_class, record_id: str):
    """Apply a delete operation"""
    try:
        record = model_class.query.get(record_id)
        if record:
            # Check if this is a soft delete model
            if hasattr(record, 'is_active'):
                # Soft delete
                record.is_active = False
                if hasattr(record, 'updated_at'):
                    record.updated_at = datetime.now(timezone.utc)
            else:
                # Hard delete
                db.session.delete(record)
            
            db.session.commit()
            return {'success': True, 'action': 'deleted'}
        else:
            return {'success': True, 'action': 'already_deleted'}
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Error in apply_delete: {e}")
        return {'success': False, 'error': str(e)}

def process_datetime_fields(record_data: Dict) -> Dict:
    """Process datetime fields in record data"""
    processed_data = {}
    
    for key, value in record_data.items():
        if is_datetime_field(key):
            processed_data[key] = parse_datetime_string(value, key)
        else:
            processed_data[key] = value
    
    return processed_data

@realtime_api.route('/ping', methods=['GET'])
def ping_realtime():
    """Health check for real-time replication"""
    return jsonify({
        'status': 'ok',
        'service': 'real-time-replication',
        'timestamp': datetime.now(timezone.utc).isoformat()
    })
