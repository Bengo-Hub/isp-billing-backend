@echo off
REM ISP Billing System - Backend Setup Script for Windows
REM This script sets up the development environment

echo 🚀 Setting up ISP Billing System Backend...

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed or not in PATH
    pause
    exit /b 1
)

echo ✅ Python is installed

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo 📦 Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo 🔧 Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo ⬆️ Upgrading pip...
python -m pip install --upgrade pip

REM Install dependencies
echo 📚 Installing dependencies...
pip install -r requirements-dev.txt

REM Create .env file if it doesn't exist
if not exist ".env" (
    echo ⚙️ Creating .env file...
    copy env.example .env
    echo 📝 Please edit .env file with your configuration
)

REM Initialize database
echo 🗄️ Initializing database...
python scripts\init_db.py

REM Create admin user
echo 👤 Creating admin user...
python scripts\create_admin.py

echo ✅ Setup completed successfully!
echo.
echo 🎉 Next steps:
echo 1. Edit .env file with your configuration
echo 2. Start the development server: uvicorn app.main:app --reload
echo 3. Or use Docker: docker-compose up -d
echo.
echo 📖 API Documentation will be available at:
echo    - Swagger UI: http://localhost:8000/docs
echo    - ReDoc: http://localhost:8000/redoc
echo.
echo 🔑 Default admin credentials:
echo    Username: admin
echo    Password: admin123
echo    (Please change the password after first login!)
echo.
pause
