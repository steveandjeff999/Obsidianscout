"""
Usage Examples for Concurrent SQLite Operations

This file demonstrates how to use the concurrent database features
in your scouting application with CR-SQLite and BEGIN CONCURRENT support.
"""

import time
from datetime import datetime
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import User, Team, ScoutingData, Match
from app import db
from app.utils.concurrent_models import (
    with_concurrent_db, 
    concurrent_batch,
    concurrent_bulk_insert,
    concurrent_update,
    ConcurrentQuery
)
from app.utils.database_manager import concurrent_db_manager, execute_concurrent_query

def example_concurrent_reads():
    """Example of performing concurrent read operations"""
    
    # Method 1: Using the concurrent model mixin
    users = User.concurrent_all()
    user_count = User.concurrent_count()
    specific_user = User.concurrent_get(1)
    filtered_users = User.concurrent_filter_by(scouting_team_number=5454)
    
    print(f"Total users: {user_count}")
    print(f"Team 5454 users: {len(filtered_users)}")
    
    # Method 2: Using ConcurrentQuery directly
    team_query = ConcurrentQuery(Team)
    all_teams = team_query.all()
    team_count = team_query.count()
    
    print(f"Total teams: {team_count}")
    
    # Method 3: Using raw SQL with concurrent execution
    results = execute_concurrent_query(
        "SELECT team_number, name FROM team WHERE active = :active",
        {'active': True},
        readonly=True
    )
    
    return {
        'users': len(users),
        'teams': len(all_teams),
        'active_teams': len(results)
    }

def example_concurrent_writes():
    """Example of performing concurrent write operations"""
    
    # Method 1: Using the concurrent model mixin for single operations
    new_user = User(
        username='concurrent_user',
        email='concurrent@example.com',
        scouting_team_number=5454
    )
    new_user.concurrent_save()
    
    # Method 2: Bulk insert with concurrent support
    team_data = [
        {'number': 1000, 'name': 'Test Team 1', 'active': True},
        {'number': 1001, 'name': 'Test Team 2', 'active': True},
        {'number': 1002, 'name': 'Test Team 3', 'active': True}
    ]
    Team.concurrent_bulk_create(team_data)
    
    # Method 3: Using batch operations for multiple writes
    with concurrent_batch() as batch:
        batch.add_insert('scouting_data', {
            'team_number': 5454,
            'match_number': 1,
            'data': '{"autonomous": {"points": 10}}',
            'scouting_team_number': 5454
        })
        
        batch.add_update('team', 5454, active=True, name='Updated Team Name')
        
        batch.add_insert('matches', {
            'number': 101,
            'type': 'Qualification',
            'red1': 5454,
            'red2': 1000,
            'red3': 1001,
            'blue1': 1002,
            'blue2': 2000,
            'blue3': 3000
        })
    
    print("Batch operations completed successfully")

@with_concurrent_db(readonly=False, retries=5)
def example_with_decorator():
    """Example using the decorator for automatic retry on conflicts"""
    
    # This function will automatically retry up to 5 times if there are database conflicts
    user = User.query.filter_by(username='test_user').first()
    if user:
        user.last_login = datetime.utcnow()
        db.session.commit()
    
    return user

def example_high_concurrency_scenario():
    """Example of handling high concurrency scenarios"""
    
    import threading
    import time
    from datetime import datetime
    
    def concurrent_writer(thread_id):
        """Function to simulate concurrent writes from multiple threads"""
        try:
            # Create scouting data entries
            for i in range(10):
                data = {
                    'team_number': 5454 + (thread_id * 100),
                    'match_number': i + 1,
                    'data': f'{{"thread_id": {thread_id}, "entry": {i}}}',
                    'scouting_team_number': 5454,
                    'timestamp': datetime.utcnow()
                }
                
                # Use concurrent write with automatic retry
                execute_concurrent_query(
                    """INSERT INTO scouting_data 
                       (team_number, match_number, data, scouting_team_number, timestamp) 
                       VALUES (:team_number, :match_number, :data, :scouting_team_number, :timestamp)""",
                    data,
                    readonly=False
                )
                
                time.sleep(0.01)  # Small delay to increase contention
                
            print(f"Thread {thread_id} completed successfully")
            
        except Exception as e:
            print(f"Thread {thread_id} failed: {e}")
    
    # Start multiple threads to simulate concurrent access
    threads = []
    for i in range(5):
        thread = threading.Thread(target=concurrent_writer, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    print("All concurrent operations completed")

def example_transaction_isolation():
    """Example demonstrating transaction isolation with CR-SQLite"""
    
    def transaction_1():
        """First transaction - update team data"""
        with concurrent_db_manager.get_connection(readonly=False) as conn:
            # Start concurrent transaction
            conn.execute("BEGIN CONCURRENT")
            
            # Update team information
            conn.execute(
                "UPDATE team SET name = :name WHERE number = :number",
                {'name': 'Updated Name 1', 'number': 5454}
            )
            
            # Simulate some processing time
            time.sleep(0.1)
            
            
            conn.commit()
    
    def transaction_2():
        """Second transaction - update different team data"""
        with concurrent_db_manager.get_connection(readonly=False) as conn:
            # Start concurrent transaction
            conn.execute("BEGIN CONCURRENT")
            
            # Update different team
            conn.execute(
                "UPDATE team SET name = :name WHERE number = :number",
                {'name': 'Updated Name 2', 'number': 1000}
            )
            
            # Simulate some processing time
            time.sleep(0.1)
            
            
            conn.commit()
    
    # Run both transactions concurrently
    import threading
    
    thread1 = threading.Thread(target=transaction_1)
    thread2 = threading.Thread(target=transaction_2)
    
    thread1.start()
    thread2.start()
    
    thread1.join()
    thread2.join()
    
    print("Concurrent transactions completed successfully")

def example_error_handling():
    """Example of proper error handling with concurrent operations"""
    
    try:
        # Attempt a potentially conflicting operation
        with concurrent_batch() as batch:
            batch.add_insert('user', {
                'username': 'duplicate_user',
                'email': 'test@example.com',
                'scouting_team_number': 5454
            })
            
            # This might conflict with existing data
            batch.add_insert('user', {
                'username': 'duplicate_user',  # Same username
                'email': 'another@example.com',
                'scouting_team_number': 5454
            })
            
    except IntegrityError as e:
        print(f"Integrity constraint violation: {e}")
        # Handle duplicate key or constraint violations
        
    except OperationalError as e:
        print(f"Database operation error: {e}")
        # Handle database locked, busy, or other operational errors
        
    except Exception as e:
        print(f"Unexpected error: {e}")
        # Handle other unexpected errors

def example_performance_monitoring():
    """Example of monitoring concurrent database performance"""
    
    import time
    
    # Get initial database info
    db_info = concurrent_db_manager.get_database_info()
    pool_stats = concurrent_db_manager.get_connection_stats()
    
    print("Database Configuration:")
    print(f"  SQLite Version: {db_info.get('sqlite_version')}")
    print(f"  Journal Mode: {db_info.get('journal_mode')}")
    print(f"  CR-SQLite: {'Available' if db_info.get('crsqlite_version') else 'Not Available'}")
    print(f"  Concurrent Writes: {db_info.get('concurrent_writes')}")
    
    print("\nConnection Pool Stats:")
    print(f"  Pool Size: {pool_stats.get('pool_size')}")
    print(f"  Checked Out: {pool_stats.get('checked_out')}")
    print(f"  Checked In: {pool_stats.get('checked_in')}")
    
    # Perform operations and measure performance
    start_time = time.time()
    
    # Concurrent reads
    users = User.concurrent_all()
    teams = Team.concurrent_all()
    
    read_time = time.time() - start_time
    
    # Concurrent writes
    start_time = time.time()
    
    test_data = [
        {'team_number': 9999, 'match_number': i, 'data': f'{{"test": {i}}}', 'scouting_team_number': 5454}
        for i in range(100)
    ]
    ScoutingData.concurrent_bulk_create(test_data)
    
    write_time = time.time() - start_time
    
    print(f"\nPerformance Results:")
    print(f"  Read time: {read_time:.3f} seconds")
    print(f"  Write time (100 records): {write_time:.3f} seconds")
    print(f"  Write rate: {100/write_time:.1f} records/second")

if __name__ == "__main__":
    # Run examples (make sure Flask app context is available)
    print("Running concurrent database operation examples...")
    
    try:
        example_concurrent_reads()
        example_concurrent_writes()
        example_high_concurrency_scenario()
        example_transaction_isolation()
        example_performance_monitoring()
        
        print("All examples completed successfully!")
        
    except Exception as e:
        print(f"Error running examples: {e}")
        import traceback
        traceback.print_exc()
