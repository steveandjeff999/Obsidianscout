"""
SQLAlchemy Integration for Concurrent Database Operations

This module provides decorators and utilities to seamlessly integrate
concurrent database operations with existing SQLAlchemy models and queries.
"""

import functools
import logging
from typing import Any, Callable, Optional
from flask import current_app
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError
from app.utils.database_manager import concurrent_db_manager, execute_concurrent_query

logger = logging.getLogger(__name__)

def with_concurrent_db(readonly: bool = False, retries: int = 3):
    """
    Decorator to execute database operations with concurrent support
    
    Args:
        readonly: Whether the operation is read-only
        retries: Number of retry attempts for conflicted transactions
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except (OperationalError, IntegrityError) as e:
                    last_exception = e
                    error_msg = str(e).lower()
                    
                    if any(keyword in error_msg for keyword in [
                        'database is locked',
                        'busy',
                        'conflict',
                        'concurrent'
                    ]):
                        logger.warning(f"Database conflict in {func.__name__}, attempt {attempt + 1}")
                        if attempt < retries - 1:
                            continue
                    
                    raise e
                except Exception as e:
                    raise e
            
            raise last_exception
            
        return wrapper
    return decorator

class ConcurrentQuery:
    """
    A helper class to execute SQLAlchemy queries with concurrent support
    """
    
    def __init__(self, model_class):
        self.model_class = model_class
        
    def get_table_name(self):
        """Get the table name for this model"""
        if hasattr(self.model_class, '__tablename__'):
            return self.model_class.__tablename__
        else:
            # Convert CamelCase to snake_case for default table name
            import re
            table_name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', self.model_class.__name__)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', table_name).lower()
        
    def get(self, id_value):
        """Get a record by ID with concurrent read"""
        table_name = self.get_table_name()
        query = f"SELECT * FROM {table_name} WHERE id = :id"
        
        result = execute_concurrent_query(query, {'id': id_value}, readonly=True)
        if result:
            return self._convert_to_model(result[0])
        return None
    
    def filter_by(self, **kwargs):
        """Filter records with concurrent read"""
        table_name = self.get_table_name()
        
        where_clauses = []
        params = {}
        
        for key, value in kwargs.items():
            where_clauses.append(f"{key} = :{key}")
            params[key] = value
        
        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        query = f"SELECT * FROM {table_name} WHERE {where_clause}"
        
        results = execute_concurrent_query(query, params, readonly=True)
        return [self._convert_to_model(row) for row in results]
    
    def all(self):
        """Get all records with concurrent read"""
        table_name = self.get_table_name()
        query = f"SELECT * FROM {table_name}"
        
        results = execute_concurrent_query(query, readonly=True)
        return [self._convert_to_model(row) for row in results]
    
    def count(self):
        """Count records with concurrent read"""
        table_name = self.get_table_name()
        query = f"SELECT COUNT(*) FROM {table_name}"
        
        result = execute_concurrent_query(query, readonly=True)
        return result[0][0] if result else 0
    
    def _convert_to_model(self, row):
        """Convert database row to model instance"""
        # This is a simplified conversion - in a real implementation,
        # you'd want to properly map the columns to model attributes
        instance = self.model_class()
        if hasattr(row, '_asdict'):
            # Handle named tuple results
            for key, value in row._asdict().items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
        else:
            # Handle dictionary-like results
            for key, value in row.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
        return instance

def concurrent_bulk_insert(model_class, data_list):
    """
    Perform bulk insert with concurrent support
    
    Args:
        model_class: SQLAlchemy model class
        data_list: List of dictionaries containing data to insert
    """
    # Get table name - either explicit or derived from class name
    if hasattr(model_class, '__tablename__'):
        table_name = model_class.__tablename__
    else:
        # Convert CamelCase to snake_case for default table name
        import re
        table_name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', model_class.__name__)
        table_name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', table_name).lower()
    
    # Convert model instances to dictionaries if needed
    if data_list and hasattr(data_list[0], '__dict__'):
        data_list = [
            {k: v for k, v in item.__dict__.items() if not k.startswith('_')}
            for item in data_list
        ]
    
    return concurrent_db_manager.bulk_insert_concurrent(table_name, data_list)

def concurrent_update(model_class, id_value, **updates):
    """
    Update a record with concurrent support
    
    Args:
        model_class: SQLAlchemy model class
        id_value: ID of the record to update
        **updates: Fields to update
    """
    # Get table name
    if hasattr(model_class, '__tablename__'):
        table_name = model_class.__tablename__
    else:
        import re
        table_name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', model_class.__name__)
        table_name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', table_name).lower()
    
    set_clauses = []
    params = {'id': id_value}
    
    for key, value in updates.items():
        set_clauses.append(f"{key} = :{key}")
        params[key] = value
    
    set_clause = ", ".join(set_clauses)
    query = f"UPDATE {table_name} SET {set_clause} WHERE id = :id"
    
    return execute_concurrent_query(query, params, readonly=False)

def concurrent_delete(model_class, id_value):
    """
    Delete a record with concurrent support
    
    Args:
        model_class: SQLAlchemy model class
        id_value: ID of the record to delete
    """
    # Get table name
    if hasattr(model_class, '__tablename__'):
        table_name = model_class.__tablename__
    else:
        import re
        table_name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', model_class.__name__)
        table_name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', table_name).lower()
    
    query = f"DELETE FROM {table_name} WHERE id = :id"
    
    return execute_concurrent_query(query, {'id': id_value}, readonly=False)

# Mixin class to add concurrent operations to SQLAlchemy models
class ConcurrentModelMixin:
    """
    Mixin to add concurrent database operations to SQLAlchemy models
    """
    
    @classmethod
    def concurrent_query(cls):
        """Get a concurrent query object for this model"""
        return ConcurrentQuery(cls)
    
    @classmethod
    def concurrent_get(cls, id_value):
        """Get a record by ID using concurrent read"""
        return cls.concurrent_query().get(id_value)
    
    @classmethod
    def concurrent_filter_by(cls, **kwargs):
        """Filter records using concurrent read"""
        return cls.concurrent_query().filter_by(**kwargs)
    
    @classmethod
    def concurrent_all(cls):
        """Get all records using concurrent read"""
        return cls.concurrent_query().all()
    
    @classmethod
    def concurrent_count(cls):
        """Count records using concurrent read"""
        return cls.concurrent_query().count()
    
    @classmethod
    def concurrent_bulk_create(cls, data_list):
        """Bulk create records using concurrent write"""
        return concurrent_bulk_insert(cls, data_list)
    
    def concurrent_save(self):
        """Save this instance using concurrent write"""
        # Convert instance to dict
        data = {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
        
        if hasattr(self, 'id') and self.id:
            # Update existing record
            return concurrent_update(self.__class__, self.id, **data)
        else:
            # Insert new record
            return concurrent_bulk_insert(self.__class__, [data])
    
    def concurrent_delete(self):
        """Delete this instance using concurrent write"""
        if hasattr(self, 'id') and self.id:
            return concurrent_delete(self.__class__, self.id)
        raise ValueError("Cannot delete instance without ID")

# Context manager for batch operations
class ConcurrentBatch:
    """
    Context manager for batching multiple concurrent operations
    """
    
    def __init__(self):
        self.operations = []
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and self.operations:
            # Execute all operations in a single transaction
            concurrent_db_manager.execute_transaction(self.operations)
    
    def add_query(self, query: str, params: Optional[dict] = None):
        """Add a query to the batch"""
        self.operations.append((query, params))
    
    def add_insert(self, table_name: str, data: dict):
        """Add an insert operation to the batch"""
        columns = list(data.keys())
        placeholders = ', '.join([f':{col}' for col in columns])
        query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        self.operations.append((query, data))
    
    def add_update(self, table_name: str, id_value: Any, **updates):
        """Add an update operation to the batch"""
        set_clauses = []
        params = {'id': id_value}
        
        for key, value in updates.items():
            set_clauses.append(f"{key} = :{key}")
            params[key] = value
        
        set_clause = ", ".join(set_clauses)
        query = f"UPDATE {table_name} SET {set_clause} WHERE id = :id"
        self.operations.append((query, params))
    
    def add_delete(self, table_name: str, id_value: Any):
        """Add a delete operation to the batch"""
        query = f"DELETE FROM {table_name} WHERE id = :id"
        self.operations.append((query, {'id': id_value}))

# Convenience function for batch operations
def concurrent_batch():
    """Create a new concurrent batch context manager"""
    return ConcurrentBatch()
