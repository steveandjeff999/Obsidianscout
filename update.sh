#!/bin/bash

echo "Starting update process..."
echo "======================="

echo "Pulling latest code from Git repository..."
git pull

echo "Installing/updating Python dependencies..."
pip install -r requirements.txt

echo "Running database migrations..."
flask db upgrade

echo "Update completed successfully!"
echo "======================="
echo "A server restart is required to apply all changes."
