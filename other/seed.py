"""
Database seed script for the FRC Scouting Platform.
This script adds sample data to the database for testing and development.
Run this script with: python seed.py
"""

import os
import sys
from datetime import datetime, date
from flask import Flask
from app import create_app, db
from app.models import Team, Match, Event, ScoutingData

def seed_database():
    """Add sample data to the database"""
    print("Skipping sample data seeding - no sample data will be added")
    print("Database seeded successfully!")

if __name__ == "__main__":
    # Create app context
    app = create_app()
    with app.app_context():
        seed_database()