"""Test runner for MPESA integration tests.

This script provides a comprehensive test runner for all MPESA-related tests
with proper configuration and reporting.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import pytest
import sys
import os
from pathlib import Path

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

def run_mpesa_tests():
    """Run all MPESA integration tests."""
    print("🧪 Running MPESA Integration Tests")
    print("=" * 50)
    
    # Test files to run
    test_files = [
        "tests/test_mpesa_integration.py",
        "tests/test_mpesa_service.py", 
        "tests/test_mpesa_api.py",
        "tests/test_mpesa_schemas.py"
    ]
    
    # Test configuration
    pytest_args = [
        "-v",  # Verbose output
        "--tb=short",  # Short traceback format
        "--strict-markers",  # Strict marker checking
        "--disable-warnings",  # Disable warnings
        "--color=yes",  # Colored output
        "--durations=10",  # Show 10 slowest tests
        "-x",  # Stop on first failure
    ]
    
    # Add test files
    pytest_args.extend(test_files)
    
    print(f"Running tests: {', '.join(test_files)}")
    print(f"Pytest arguments: {' '.join(pytest_args)}")
    print()
    
    # Run tests
    exit_code = pytest.main(pytest_args)
    
    if exit_code == 0:
        print("\n✅ All MPESA tests passed!")
    else:
        print(f"\n❌ Tests failed with exit code: {exit_code}")
    
    return exit_code

def run_specific_test(test_name: str):
    """Run a specific test file or test function."""
    print(f"🧪 Running specific test: {test_name}")
    print("=" * 50)
    
    pytest_args = [
        "-v",
        "--tb=short",
        "--color=yes",
        f"tests/{test_name}"
    ]
    
    exit_code = pytest.main(pytest_args)
    return exit_code

def run_with_coverage():
    """Run tests with coverage reporting."""
    print("🧪 Running MPESA tests with coverage")
    print("=" * 50)
    
    pytest_args = [
        "-v",
        "--tb=short",
        "--color=yes",
        "--cov=app.integrations.mpesa",
        "--cov=app.services.mpesa_service",
        "--cov=app.api.v1.mpesa",
        "--cov=app.schemas.mpesa",
        "--cov-report=html",
        "--cov-report=term-missing",
        "tests/test_mpesa_integration.py",
        "tests/test_mpesa_service.py",
        "tests/test_mpesa_api.py",
        "tests/test_mpesa_schemas.py"
    ]
    
    exit_code = pytest.main(pytest_args)
    return exit_code

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run MPESA integration tests")
    parser.add_argument(
        "--test", 
        help="Run specific test file (e.g., test_mpesa_integration.py)"
    )
    parser.add_argument(
        "--coverage", 
        action="store_true", 
        help="Run tests with coverage reporting"
    )
    
    args = parser.parse_args()
    
    if args.test:
        exit_code = run_specific_test(args.test)
    elif args.coverage:
        exit_code = run_with_coverage()
    else:
        exit_code = run_mpesa_tests()
    
    sys.exit(exit_code)
