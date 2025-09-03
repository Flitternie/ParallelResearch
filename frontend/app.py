from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO, emit
import asyncio
import json
import os
import time
import logging
from datetime import datetime
from threading import Thread
import uuid
from typing import Dict, Any, Optional
import weakref

# Setup logging
logger = logging.getLogger(__name__)

# Get configuration from environment variables (set by frontend.py launcher)
run_config = os.environ.get('FRONTEND_CONFIG_PATH', './config.json')
research_module_name = os.environ.get('FRONTEND_RESEARCH_MODULE', 'flash_research_runtime')

# Dynamic import of the research module
DeepResearch = None
ResearchVisualizer = None

def load_research_module(module_name):
    """Dynamically load the specified research module"""
    global DeepResearch
    
    try:
        if module_name == 'baseline':
            from modified_deep_research import DeepResearch
        elif module_name == 'parallel':
            from modified_parallel_deep_research import ParallelizedDeepResearch as DeepResearch
        elif module_name == 'recursive':
            from recursive_deep_research import DeepResearch
        elif module_name == 'runtime':
            from flash_research_runtime import FlashResearchRuntime as DeepResearch
        else:
            logger.error(f"Unknown research module: {module_name}")
            return False
            
        logger.info(f"Successfully loaded research module: {module_name}")
        return True
    except ImportError as e:
        logger.error(f"Failed to import research module {module_name}: {e}")
        return False

# Load the specified research module
load_research_module(research_module_name)

# Try to load visualizer
try:
    from research_visualizer_d3 import ResearchVisualizer
except ImportError as e:
    logger.error(f"Import error for visualizer: {e}")
    ResearchVisualizer = None
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global storage for active research sessions
active_sessions: Dict[str, Dict[str, Any]] = {}

def setup_environment():
    """Setup environment variables for the research system"""
    try:
        os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
        os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()
        os.environ["BRAVE_API_KEY"] = open("./brave.key").read().strip()
        os.environ["CUSTOM_EMBED_API_KEY"] = open("./openai.key").read().strip()
        # os.environ["CUSTOM_EMBED_BASE_URL"] = open("openai_url.key").read().strip()
        os.environ["CUSTOM_EMBED_BASE_URL"] = "http://0.0.0.0:8000/v1/"
        return True
    except Exception as e:
        logger.error(f"Error setting up environment: {e}")
        return False

def run_async_research(session_id: str, query: str, config_path: str, logs_dir: str):
    """Run async research in a separate thread"""
    import threading
    import time
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    
    class ProgressFileHandler(FileSystemEventHandler):
        def __init__(self, session_id, logs_dir):
            self.session_id = session_id
            self.logs_dir = logs_dir
            self.last_modified = 0
            
        def on_modified(self, event):
            if event.src_path.endswith('progress.json'):
                # Avoid duplicate events
                current_time = time.time()
                if current_time - self.last_modified < 0.5:  # 500ms debounce
                    return
                self.last_modified = current_time
                
                # Send visualization update
                try:
                    if ResearchVisualizer is not None:
                        visualizer = ResearchVisualizer(event.src_path)
                        log_data = visualizer.load_log()
                        if log_data and 'nodes' in log_data:
                            # Convert nodes dictionary to array for frontend compatibility
                            nodes_array = list(log_data['nodes'].values()) if isinstance(log_data['nodes'], dict) else log_data['nodes']
                            socketio.emit('visualization_update', {
                                'session_id': self.session_id,
                                'nodes': nodes_array,
                                'edges': log_data.get('edges', [])
                            }, room=self.session_id)
                            logger.info(f"Sent visualization update with {len(nodes_array)} nodes")
                except Exception as e:
                    logger.error(f"Error updating visualization: {e}")
    
    async def research_task():
        observer = None
        try:
            # Configure logging for this session
            session_logger = logging.getLogger('modified_parallel_deep_research')
            session_logger.setLevel(logging.DEBUG)
            
            # Add file handler for session-specific logging
            file_handler = logging.FileHandler(f"{logs_dir}/deep_research.log")
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            session_logger.addHandler(file_handler)
            
            # Also add console handler to see logs in real-time
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            session_logger.addHandler(console_handler)
            
            logger.info(f"Session logging configured for {logs_dir}")
            
            # Update session status
            if session_id in active_sessions:
                active_sessions[session_id]['status'] = 'running'
                socketio.emit('status_update', {
                    'session_id': session_id,
                    'status': 'running',
                    'message': 'Research started...'
                }, room=session_id)

            # Set up file watcher for progress.json
            try:
                from watchdog.observers import Observer
                from watchdog.events import FileSystemEventHandler
                
                event_handler = ProgressFileHandler(session_id, logs_dir)
                observer = Observer()
                observer.schedule(event_handler, logs_dir, recursive=False)
                observer.start()
                logger.info(f"Started file watcher for {logs_dir}")
            except ImportError:
                logger.warning("Watchdog not available, using polling for visualization updates")
                observer = None

            # Create progress callback for direct logger updates
            def on_logger_update(update_data):
                if update_data.get('type') == 'visualization_update':
                    # Convert nodes dictionary to array for frontend compatibility
                    nodes_data = update_data.get('nodes', [])
                    nodes_array = list(nodes_data.values()) if isinstance(nodes_data, dict) else nodes_data
                    socketio.emit('visualization_update', {
                        'session_id': session_id,
                        'nodes': nodes_array,
                        'edges': update_data.get('edges', [])
                    }, room=session_id)
                    logger.info(f"Sent visualization update with {len(nodes_array)} nodes")
                    
                    # Send status change notification if present
                    if 'status_notification' in update_data:
                        notification = update_data['status_notification']
                        node_id = notification['node_id']
                        new_status = notification['new_status']
                        node_query = notification['node_query'][:100] + "..." if len(notification['node_query']) > 100 else notification['node_query']
                        
                        status_icon = "🔴" if new_status == "terminated" else "⚠️"  # Red circle for terminated, warning for cancelled
                        message = f"{status_icon} Node {node_id} {new_status}: {node_query}"
                        
                        socketio.emit('status_notification', {
                            'session_id': session_id,
                            'type': 'warning' if new_status == 'cancelled' else 'error',
                            'message': message,
                            'node_id': node_id,
                            'status': new_status
                        }, room=session_id)
                        logger.info(f"Sent status notification for node {node_id}: {new_status}")

            # Create research instance with progress callback
            # NOTE: Depth will be taken from CONFIG (MAX_DEPTH)
            logger.info(f"Creating DeepResearch instance with query: {query[:100]}...")
            logger.info(f"Using config file: {config_path}")
            
            deep_researcher = DeepResearch(
                query=query, 
                config_path=config_path, 
                logs_dir=logs_dir,
                progress_callback=on_logger_update
            )
            
            logger.info(f"DeepResearch instance created with depth: {deep_researcher.depth}")
            logger.info(f"DeepResearch config max_depth: {deep_researcher.config.max_depth}")
            logger.info(f"DeepResearch config max_breadth: {deep_researcher.config.max_breadth}")
            
            # Progress callback - this will be called less frequently
            def on_progress(progress_data):
                try:
                    # Convert ResearchProgress object to dictionary for JSON serialization
                    if hasattr(progress_data, '__dict__'):
                        progress_dict = progress_data.__dict__.copy()
                    elif hasattr(progress_data, 'to_dict'):
                        progress_dict = progress_data.to_dict()
                    else:
                        progress_dict = {'status': str(progress_data)}
                    
                    socketio.emit('progress_update', {
                        'session_id': session_id,
                        'progress': progress_dict
                    }, room=session_id)
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")
                    # Send basic progress info as fallback
                    socketio.emit('progress_update', {
                        'session_id': session_id,
                        'progress': {'status': 'processing'}
                    }, room=session_id)
                
                # Also send visualization update as backup
                if observer is None:  # Only if file watcher is not available
                    try:
                        if ResearchVisualizer is not None:
                            visualizer = ResearchVisualizer(f"{logs_dir}/progress.json")
                            if os.path.exists(f"{logs_dir}/progress.json"):
                                log_data = visualizer.load_log()
                                if log_data and 'nodes' in log_data:
                                    # Convert nodes dictionary to array for frontend compatibility
                                    nodes_array = list(log_data['nodes'].values()) if isinstance(log_data['nodes'], dict) else log_data['nodes']
                                    socketio.emit('visualization_update', {
                                        'session_id': session_id,
                                        'nodes': nodes_array,
                                        'edges': log_data.get('edges', [])
                                    }, room=session_id)
                    except Exception as e:
                        logger.error(f"Error updating visualization: {e}")

            # Start periodic polling as additional backup if no file watcher
            polling_active = True
            def poll_progress_file():
                while polling_active and session_id in active_sessions:
                    try:
                        if ResearchVisualizer is not None and os.path.exists(f"{logs_dir}/progress.json"):
                            visualizer = ResearchVisualizer(f"{logs_dir}/progress.json")
                            log_data = visualizer.load_log()
                            if log_data and 'nodes' in log_data:
                                # Convert nodes dictionary to array for frontend compatibility
                                nodes_array = list(log_data['nodes'].values()) if isinstance(log_data['nodes'], dict) else log_data['nodes']
                                socketio.emit('visualization_update', {
                                    'session_id': session_id,
                                    'nodes': nodes_array,
                                    'edges': log_data.get('edges', [])
                                }, room=session_id)
                    except Exception as e:
                        logger.error(f"Polling error: {e}")
                    
                    time.sleep(2)  # Poll every 2 seconds
            
            # Start polling thread as backup
            if observer is None:
                polling_thread = threading.Thread(target=poll_progress_file, daemon=True)
                polling_thread.start()

            # Run research
            report = await deep_researcher.run(on_progress=on_progress)
            
            # Stop polling
            polling_active = False
            
            # Stop file observer
            if observer:
                observer.stop()
                observer.join()
            
            # Save report
            report_path = f"{logs_dir}/report.md"
            with open(report_path, "w") as f:
                f.write(report)
            
            # Generate final visualization
            try:
                if ResearchVisualizer is not None:
                    visualizer = ResearchVisualizer(f"{logs_dir}/progress.json")
                    visualization_path = f"{logs_dir}/final_visualization.html"
                    visualizer.visualize(visualization_path)
            except Exception as e:
                logger.error(f"Error generating final visualization: {e}")
            
            # Update session with results
            if session_id in active_sessions:
                active_sessions[session_id].update({
                    'status': 'completed',
                    'report': report,
                    'report_path': report_path,
                    'visualization_path': visualization_path,
                    'end_time': datetime.now().isoformat()
                })
                
                # Send completion notification
                socketio.emit('research_complete', {
                    'session_id': session_id,
                    'status': 'completed',
                    'report': report,
                    'message': 'Research completed successfully!'
                }, room=session_id)
                
        except Exception as e:
            logger.error(f"Research error for session {session_id}: {e}")
            
            # Stop polling
            try:
                polling_active = False
            except:
                pass
                
            # Stop file observer
            try:
                if observer:
                    observer.stop()
                    observer.join()
            except:
                pass
                
            if session_id in active_sessions:
                active_sessions[session_id]['status'] = 'error'
                active_sessions[session_id]['error'] = str(e)
                
            socketio.emit('research_error', {
                'session_id': session_id,
                'status': 'error',
                'error': str(e),
                'message': f'Research failed: {str(e)}'
            }, room=session_id)
        finally:
            # Clean up logging handlers
            try:
                session_logger = logging.getLogger('modified_parallel_deep_research')
                # Remove all handlers to prevent memory leaks
                for handler in session_logger.handlers[:]:
                    session_logger.removeHandler(handler)
                    handler.close()
            except:
                pass

    # Run in event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(research_task())
    finally:
        loop.close()

@app.route('/')
def index():
    """Main application page"""
    # Create a friendly display name for the research module
    module_display_names = {
        'runtime': 'Flash Research',
        'baseline': 'Deep Research',
        'parallel': 'Parallel Research',
        'recursive': 'Parallel Research'
    }
    
    # Different icons for different modules
    module_icons = {
        'runtime': '⚡️',
        'baseline': '🔬',
        'parallel': '🚀',
        'recursive': '🚀'
    }
    
    display_name = module_display_names.get(research_module_name, research_module_name.replace('_', ' ').title())
    icon = module_icons.get(research_module_name, '🔬')
    
    return render_template('index.html', 
                         research_module=research_module_name,
                         display_name=display_name,
                         config_path=run_config,
                         icon=icon)

@app.route('/api/config')
def get_config_info():
    """Get current configuration information"""
    return jsonify({
        'config_path': run_config,
        'research_module': research_module_name,
        'research_module_available': DeepResearch is not None,
        'visualizer_available': ResearchVisualizer is not None
    })

@app.route('/api/start_research', methods=['POST'])
def start_research():
    """Start a new research session"""
    if DeepResearch is None:
        return jsonify({
            'error': f'Research module "{research_module_name}" not available. Please check dependencies.'
        }), 500
        
    if not setup_environment():
        return jsonify({'error': 'Failed to setup environment. Check API keys.'}), 500
    
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    logger.info(f"Starting research with module: {research_module_name}, config: {run_config}")
    
    # Generate session ID and create logs directory
    session_id = str(uuid.uuid4())
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    logs_dir = f"logs/frontend/{timestamp}_{session_id}"
    os.makedirs(logs_dir, exist_ok=True)
    
    # Note: Logging will be configured per-session in the research task
    
    # Store session info
    active_sessions[session_id] = {
        'session_id': session_id,
        'query': query,
        'status': 'initializing',
        'logs_dir': logs_dir,
        'start_time': datetime.now().isoformat(),
        'config_path': run_config,
        'research_module': research_module_name
    }
    
    # Start research in background thread
    research_thread = Thread(
        target=run_async_research,
        args=(session_id, query, run_config, logs_dir)
    )
    research_thread.daemon = True
    research_thread.start()
    
    return jsonify({
        'session_id': session_id,
        'status': 'initializing',
        'message': f'Research session started using {research_module_name}',
        'config_path': run_config,
        'research_module': research_module_name
    })

@app.route('/api/session/<session_id>/status')
def get_session_status(session_id: str):
    """Get status of a research session"""
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session = active_sessions[session_id]
    return jsonify({
        'session_id': session_id,
        'status': session['status'],
        'query': session['query'],
        'start_time': session['start_time'],
        'report': session.get('report', ''),
        'error': session.get('error', ''),
        'config_path': session.get('config_path', run_config),
        'research_module': session.get('research_module', research_module_name)
    })

@app.route('/api/session/<session_id>/visualization')
def get_visualization_data(session_id: str):
    """Get current visualization data for a session"""
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    if ResearchVisualizer is None:
        return jsonify({'nodes': [], 'edges': [], 'start_time': '', 'error': 'Visualizer not available'})

    session = active_sessions[session_id]
    logs_dir = session['logs_dir']
    progress_file = f"{logs_dir}/progress.json"
    
    try:
        if os.path.exists(progress_file):
            visualizer = ResearchVisualizer(progress_file)
            log_data = visualizer.load_log()
            # Convert nodes dictionary to array for frontend compatibility
            nodes_data = log_data.get('nodes', [])
            nodes_array = list(nodes_data.values()) if isinstance(nodes_data, dict) else nodes_data
            return jsonify({
                'nodes': nodes_array,
                'edges': log_data.get('edges', []),
                'start_time': log_data.get('start_time', '')
            })
        else:
            return jsonify({'nodes': [], 'edges': [], 'start_time': ''})
    except Exception as e:
        logger.error(f"Error loading visualization data: {e}")
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f'Client connected: {request.sid}')
    emit('connected', {'message': 'Connected to research server'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f'Client disconnected: {request.sid}')

@socketio.on('join_session')
def handle_join_session(data):
    """Join a research session room"""
    session_id = data.get('session_id')
    if session_id:
        from flask_socketio import join_room
        join_room(session_id)
        emit('joined_session', {'session_id': session_id})

if __name__ == '__main__':
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Run the application
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
