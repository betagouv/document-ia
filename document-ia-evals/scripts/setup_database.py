#!/usr/bin/env python3
"""
Automated database setup script.

This script:
1. Checks Docker is available
2. Starts PostgreSQL container
3. Waits for database to be ready
4. Runs Alembic migrations
5. Verifies tables were created
"""

import subprocess
import sys
import time
import os
from pathlib import Path

# Colors for terminal output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_step(message):
    """Print a step message."""
    print(f"{BLUE}▶ {message}{RESET}")


def print_success(message):
    """Print a success message."""
    print(f"{GREEN}✓ {message}{RESET}")


def print_error(message):
    """Print an error message."""
    print(f"{RED}✗ {message}{RESET}")


def print_warning(message):
    """Print a warning message."""
    print(f"{YELLOW}⚠ {message}{RESET}")


def run_command(cmd, check=True, capture_output=True):
    """Run a shell command."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=check,
            capture_output=capture_output,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            print_error(f"Command failed: {cmd}")
            print_error(f"Error: {e.stderr}")
            sys.exit(1)
        return e


def check_docker():
    """Check if Docker is available."""
    print_step("Checking Docker installation...")
    result = run_command("docker --version", check=False)
    if result.returncode != 0:
        print_error("Docker is not installed or not in PATH")
        print("Please install Docker: https://docs.docker.com/get-docker/")
        sys.exit(1)
    print_success(f"Docker found: {result.stdout.strip()}")


def check_docker_compose():
    """Check if Docker Compose is available."""
    print_step("Checking Docker Compose...")
    result = run_command("docker compose version", check=False)
    if result.returncode != 0:
        print_error("Docker Compose is not available")
        print("Please install Docker Compose")
        sys.exit(1)
    print_success(f"Docker Compose found: {result.stdout.strip()}")


def start_database():
    """Start the PostgreSQL container."""
    print_step("Starting PostgreSQL container...")
    
    # Check if already running
    result = run_command("docker compose ps --services --filter status=running", check=False)
    if "postgres" in result.stdout:
        print_warning("PostgreSQL container is already running")
        return
    
    # Start the container
    result = run_command("docker compose up -d postgres", capture_output=False)
    print_success("PostgreSQL container started")


def wait_for_database(max_attempts=30, delay=1):
    """Wait for PostgreSQL to be ready."""
    print_step("Waiting for PostgreSQL to be ready...")
    
    for attempt in range(max_attempts):
        result = run_command(
            "docker compose exec -T postgres pg_isready -U postgres",
            check=False
        )
        if result.returncode == 0:
            print_success("PostgreSQL is ready")
            return True
        
        if attempt < max_attempts - 1:
            print(f"  Attempt {attempt + 1}/{max_attempts}... waiting {delay}s")
            time.sleep(delay)
    
    print_error("PostgreSQL did not become ready in time")
    sys.exit(1)


def run_migrations():
    """Run Alembic migrations."""
    print_step("Running database migrations...")
    
    result = run_command("alembic upgrade head", capture_output=False)
    print_success("Migrations completed")


def verify_tables():
    """Verify that tables were created."""
    print_step("Verifying database tables...")
    
    result = run_command(
        'docker compose exec -T postgres psql -U postgres -d experiments_db -c "\\dt"'
    )
    
    if "experiments" in result.stdout and "observations" in result.stdout:
        print_success("Database tables verified:")
        print(result.stdout)
        return True
    else:
        print_error("Expected tables not found")
        print(result.stdout)
        return False


def main():
    """Main setup function."""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}  Database Setup Script{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    # Change to project root directory
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)
    print(f"Working directory: {os.getcwd()}\n")
    
    try:
        # Run setup steps
        check_docker()
        check_docker_compose()
        start_database()
        wait_for_database()
        run_migrations()
        verify_tables()
        
        print(f"\n{GREEN}{'='*60}{RESET}")
        print(f"{GREEN}  ✓ Database setup completed successfully!{RESET}")
        print(f"{GREEN}{'='*60}{RESET}\n")
        
        print("Database connection details:")
        print(f"  Host: localhost")
        print(f"  Port: 5435")
        print(f"  Database: experiments_db")
        print(f"  User: postgres")
        print(f"  Password: postgres\n")
        
        print("Next steps:")
        print(f"  1. Run the application: {BLUE}streamlit run app.py{RESET}")
        print(f"  2. Navigate to the New Experiment page")
        print(f"  3. Start tracking your experiments!\n")
        
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Setup interrupted by user{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Unexpected error: {e}{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()