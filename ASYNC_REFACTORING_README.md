# Async Deep Research Refactoring

## Overview

This document outlines the refactoring of the `modified_parallel_deep_research.py` from a ThreadPoolExecutor-based implementation to a pure asyncio-based task management system. The refactoring provides better control over concurrent tasks, improved scalability for I/O-heavy workloads, and simplified task orchestration.

## Key Changes

### 1. Replaced Threading with Asyncio

**Before:**
```python
from threading import ThreadPoolExecutor, Lock, Event
import queue

class ThreadSafeProgress:
    def __init__(self):
        self._lock = threading.Lock()
        # ...

executor = ThreadPoolExecutor(max_workers=32)
```

**After:**
```python
import asyncio
from enum import Enum

class AsyncProgress:
    def __init__(self):
        self._lock = asyncio.Lock()
        # ...

# Using asyncio.Semaphore for concurrency control
semaphore = asyncio.Semaphore(concurrency_limit)
```

### 2. Task State Management

**New TaskState Enum:**
```python
class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

**Enhanced AsyncQueryTask:**
```python
class AsyncQueryTask:
    def __init__(self, serp_query, depth, breadth, parent_node_id, task_id):
        # ... existing fields ...
        self.state = TaskState.PENDING
        self.asyncio_task: Optional[asyncio.Task] = None
        
    def cancel(self) -> bool:
        """Cancel the task if it's running"""
        if self.asyncio_task and not self.asyncio_task.done():
            self.state = TaskState.CANCELLED
            return self.asyncio_task.cancel()
        return False
```

### 3. Async Task Manager

**Replaced ThreadSafeData with AsyncTaskManager:**
```python
class AsyncTaskManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.active_tasks: Dict[str, AsyncQueryTask] = {}
        self.completed_tasks: Dict[str, AsyncQueryTask] = {}
        # ... other fields ...
    
    async def register_task(self, task: AsyncQueryTask):
        """Register a new task"""
        async with self._lock:
            self.active_tasks[task.task_id] = task
            self.total_tasks_submitted += 1
    
    async def cancel_all_tasks(self):
        """Cancel all active tasks"""
        async with self._lock:
            for task in self.active_tasks.values():
                task.cancel()
```

### 4. Pure Async Research Pipeline

**Before (Thread-based):**
```python
def _research(self, task, thread_safe_data, thread_safe_progress, on_progress, main_loop):
    # Create new event loop in thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(researcher.conduct_research())
    finally:
        loop.close()
    
    # Submit recursive tasks to thread pool
    self.executor.submit(self._research, recursive_task, ...)
```

**After (Pure Async):**
```python
async def _async_research(self, task, task_manager, progress_tracker, on_progress):
    async with self.semaphore:  # Control concurrency
        try:
            task.state = TaskState.RUNNING
            
            # Conduct research (already async)
            await researcher.conduct_research()
            
            # Generate recursive tasks as async tasks
            await self._generate_recursive_tasks(...)
            
        except asyncio.CancelledError:
            task.state = TaskState.CANCELLED
            raise
        except Exception as e:
            task.state = TaskState.FAILED
            await task_manager.complete_task(task.task_id, error=e)
```

### 5. Dynamic Task Creation and Management

**Recursive Task Generation:**
```python
async def _generate_recursive_tasks(self, parent_result, current_depth, current_breadth, 
                                   task_manager, progress_tracker, on_progress):
    # Generate sub-queries
    sub_queries = await self.generate_serp_queries(next_query, num_queries=new_breadth)
    
    # Create and launch recursive async tasks immediately
    for serp_query in sub_queries:
        task_id = await task_manager.create_task_id()
        query_task = AsyncQueryTask(serp_query, new_depth, new_breadth, 
                                   recursive_planning_node_id, task_id)
        await task_manager.register_task(query_task)
        
        # Create and launch asyncio task immediately
        asyncio_task = asyncio.create_task(
            self._async_research(query_task, task_manager, progress_tracker, on_progress)
        )
        query_task.asyncio_task = asyncio_task
```

## Benefits of the Refactoring

### 1. **Dynamic Runtime Control**
- **Task Cancellation:** Any task can be cancelled via `task.cancel()`
- **State Monitoring:** Real-time task state tracking (pending, running, completed, cancelled, failed)
- **Timeout Management:** Tasks can be cancelled after timeout periods

### 2. **Improved Scalability**
- **No Thread Overhead:** Eliminates thread creation/destruction costs
- **Better I/O Handling:** Native async support for all I/O operations
- **Memory Efficiency:** Asyncio coroutines use less memory than threads

### 3. **Simplified Orchestration**
- **Single Event Loop:** All operations run on the main event loop
- **No Loop Management:** No need to create/close event loops in threads
- **Natural Async Flow:** Async/await throughout the pipeline

### 4. **Enhanced Monitoring**
- **Task Statistics:** Real-time stats on submitted, completed, active tasks
- **Progress Tracking:** Thread-safe progress updates
- **Error Handling:** Better exception propagation and handling

## Usage Examples

### Basic Usage (Same as Before)
```python
deep_research = DeepResearch(
    query="AI developments in 2024",
    breadth=4,
    depth=2,
    concurrency_limit=6  # Now controls async semaphore
)

report = await deep_research.run()
```

### Advanced Usage with Task Control
```python
# Start research
task = asyncio.create_task(deep_research.run())

# Monitor progress
async def monitor_progress():
    while not task.done():
        stats = await deep_research.task_manager.get_task_stats()
        print(f"Active tasks: {stats['active']}, Completed: {stats['completed']}")
        await asyncio.sleep(5)

# Cancel if needed
async def cancel_after_timeout():
    await asyncio.sleep(300)  # 5 minutes
    if not task.done():
        task.cancel()
        print("Research cancelled due to timeout")

# Run with monitoring and timeout
await asyncio.gather(
    task,
    monitor_progress(),
    cancel_after_timeout(),
    return_exceptions=True
)
```

## Migration Guide

### For Existing Code
The public API remains largely the same:
- `DeepResearch.__init__()` parameters are mostly unchanged
- `await deep_research.run()` works the same way
- Progress callbacks work the same way

### New Capabilities
- Access task manager: `deep_research.task_manager`
- Monitor task states: `await task_manager.get_task_stats()`
- Cancel all tasks: `await task_manager.cancel_all_tasks()`

### Removed Dependencies
- No more `ThreadPoolExecutor`
- No more `threading.Lock`, `threading.Event`
- No more `queue.Queue`
- Removed `max_workers` parameter (replaced by `concurrency_limit`)

## Performance Considerations

### Memory Usage
- **Reduced:** No thread stack overhead (typically 8MB per thread)
- **Efficient:** Asyncio coroutines use minimal memory

### CPU Usage
- **Lower:** No thread switching overhead
- **Better:** More efficient for I/O-bound workloads

### Scalability
- **Higher Concurrency:** Can handle thousands of concurrent tasks
- **Better Resource Utilization:** No thread pool size limitations

## Testing

Run the test suite:
```bash
python test_async_deep_research.py
```

The test suite covers:
- AsyncTaskManager functionality
- Task cancellation
- Concurrency control with semaphores
- Progress tracking
- Error handling

## Conclusion

This refactoring transforms the deep research system from a hybrid threading/async model to a pure asyncio implementation, providing:

1. **Better Control:** Dynamic task cancellation, timeout, and monitoring
2. **Improved Performance:** Lower memory usage, higher concurrency
3. **Simplified Code:** Single event loop, natural async flow
4. **Enhanced Reliability:** Better error handling and state management

The system now supports large-scale research workflows with full dynamic control at runtime, making it suitable for production environments requiring high throughput and reliability.
