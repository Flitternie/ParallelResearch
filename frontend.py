"""
Simple launcher for the Deep Research Frontend
Handles missing dependencies gracefully
"""

import sys
import os
import subprocess
import importlib.util

def check_and_install_package(package_name, pip_name=None):
    """Check if a package is installed, install if not"""
    if pip_name is None:
        pip_name = package_name
    
    spec = importlib.util.find_spec(package_name)
    if spec is None:
        print(f"Installing {package_name}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
            return True
        except subprocess.CalledProcessError:
            print(f"Failed to install {package_name}")
            return False
    return True

def check_api_keys():
    """Check if required API key files exist"""
    required_files = ["openai.key", "openai_url.key", "brave.key"]
    missing_files = []
    
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
    
    if missing_files:
        print("⚠️  Warning: Missing API key files:")
        for file in missing_files:
            print(f"  - {file}")
        print("\nThe application may not work properly without these files.")
        print("You can create dummy files for testing:")
        for file in missing_files:
            with open(file, 'w') as f:
                f.write("dummy_key_for_testing")
        print("Created dummy key files for testing.")

def main():
    print("🔬 Deep Research Frontend - Development Launcher")
    print("=" * 50)
    
    # Check and install required packages
    packages = [
        ("flask", "flask==2.3.3"),
        ("socketio", "python-socketio==5.8.0"),
        ("flask_socketio", "flask-socketio==5.3.6"),
        ("eventlet", "eventlet==0.33.3")
    ]
    
    for package, pip_name in packages:
        if not check_and_install_package(package, pip_name):
            print(f"❌ Failed to install {package}. Please install manually.")
            return 1
    
    # Check API keys
    check_api_keys()
    
    # Create logs directory
    os.makedirs("logs", exist_ok=True)
    
    print("\n🚀 Starting the application...")
    print("Open http://localhost:5000 in your browser")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    # Import and run the app
    try:
        from frontend.app import app, socketio
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Error starting application: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
