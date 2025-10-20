#!/bin/bash

# ISP Billing System - Backend Setup Script
# This script sets up the development environment

set -e

echo "🚀 Setting up ISP Billing System Backend..."

# Check if Python 3.10+ is installed
python_version=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
required_version="3.10"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python 3.10+ is required. Current version: $python_version"
    exit 1
fi

echo "✅ Python version check passed: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📚 Installing dependencies..."
pip install -r requirements-dev.txt

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "⚙️ Creating .env file..."
    cp env.example .env
    echo "📝 Please edit .env file with your configuration"
fi

# Initialize database
echo "🗄️ Initializing database..."
python scripts/init_db.py

# Create admin user
echo "👤 Creating admin user..."
python scripts/create_admin.py

echo "✅ Setup completed successfully!"
echo ""
echo "🎉 Next steps:"
echo "1. Edit .env file with your configuration"
echo "2. Start the development server: uvicorn app.main:app --reload"
echo "3. Or use Docker: docker-compose up -d"
echo ""
echo "📖 API Documentation will be available at:"
echo "   - Swagger UI: http://localhost:8000/docs"
echo "   - ReDoc: http://localhost:8000/redoc"
echo ""
echo "🔑 Default admin credentials:"
echo "   Username: admin"
echo "   Password: admin123"
echo "   (Please change the password after first login!)"
