"""
Simple launcher for the Deep Research Frontend
Handles missing dependencies gracefully
"""

import sys
import os
import subprocess
import importlib.util
import argparse

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Deep Research Frontend Launcher',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--config', 
        type=str, 
        default='./config.json',
        help='Path to the config file'
    )
    parser.add_argument(
        '--version',
        type=str,
        required=True,
        choices=['baseline', 'parallel', 'recursive', 'runtime'],
        help='Deep research module to use'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Port to run the server on (default: 5000)'
    )
    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    
    return parser.parse_args()

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
    # Parse command line arguments
    args = parse_arguments()
    
    print("🔬 Deep Research Frontend - Development Launcher")
    print("=" * 50)
    print(f"Config file: {args.config}")
    print(f"Research module: {args.version}")
    print(f"Server: {args.host}:{args.port}")
    print("=" * 50)
    
    # Validate config file exists
    if not os.path.exists(args.config):
        print(f"❌ Config file not found: {args.config}")
        return 1
    
    # Validate research module can be imported
    try:
        if args.version == 'flash_research_runtime':
            import flash_research_runtime
        elif args.version == 'modified_deep_research':
            import modified_deep_research
        elif args.version == 'modified_parallel_deep_research':
            import modified_parallel_deep_research
        elif args.version == 'recursive_deep_research':
            import recursive_deep_research
        print(f"✅ Research module '{args.version}' is available")
    except ImportError as e:
        print(f"❌ Research module '{args.version}' cannot be imported: {e}")
        return 1
    
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
    print(f"Open http://localhost:{args.port} in your browser")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    # Set environment variables for the app
    os.environ['FRONTEND_CONFIG_PATH'] = args.config
    os.environ['FRONTEND_RESEARCH_MODULE'] = args.version
    
    # Import and run the app
    try:
        from frontend.app import app, socketio
        socketio.run(app, debug=args.debug, host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Error starting application: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
