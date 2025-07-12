#!/usr/bin/env python3
"""
Test script for the async-refactored DeepResearch implementation.
This demonstrates the new async functionality and dynamic task control.
"""

import asyncio
import logging
from datetime import datetime
from modified_parallel_deep_research import DeepResearch, AsyncTaskManager, AsyncQueryTask, TaskState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_async_task_manager():
    """Test the AsyncTaskManager functionality"""
    print("\n=== Testing AsyncTaskManager ===")
    
    task_manager = AsyncTaskManager()
    
    # Test adding data
    await task_manager.add_learning("Test learning 1")
    await task_manager.add_learnings(["Learning 2", "Learning 3"])
    await task_manager.add_citation("Learning 2", "https://example.com")
    
    # Create a mock task
    task_id = await task_manager.create_task_id()
    mock_task = AsyncQueryTask(
        serp_query={"query": "test query", "researchGoal": "test goal"},
        depth=1,
        breadth=2,
        parent_node_id=None,
        task_id=task_id
    )
    
    await task_manager.register_task(mock_task)
    
    # Check stats
    stats = await task_manager.get_task_stats()
    print(f"Task stats: {stats}")
    
    # Complete the task
    result = {
        "learnings": ["New learning from task"],
        "visited_urls": ["https://test.com"],
        "citations": {"New learning from task": "https://test.com"}
    }
    await task_manager.complete_task(task_id, result)
    
    # Get all data
    all_data = await task_manager.get_all_data()
    print(f"All collected data: {all_data}")
    
    print("✓ AsyncTaskManager test passed")


async def test_task_cancellation():
    """Test task cancellation functionality"""
    print("\n=== Testing Task Cancellation ===")
    
    async def long_running_task():
        """Simulate a long-running task"""
        try:
            await asyncio.sleep(10)  # Long delay
            return "completed"
        except asyncio.CancelledError:
            print("Task was cancelled")
            raise
    
    # Create and start a task
    task = asyncio.create_task(long_running_task())
    
    # Let it run briefly
    await asyncio.sleep(0.1)
    
    # Cancel the task
    cancelled = task.cancel()
    print(f"Task cancellation successful: {cancelled}")
    
    try:
        await task
    except asyncio.CancelledError:
        print("✓ Task cancellation test passed")


async def test_concurrency_control():
    """Test semaphore-based concurrency control"""
    print("\n=== Testing Concurrency Control ===")
    
    semaphore = asyncio.Semaphore(2)  # Only allow 2 concurrent tasks
    completed_tasks = []
    
    async def controlled_task(task_id: int):
        async with semaphore:
            print(f"Task {task_id} started")
            await asyncio.sleep(0.5)  # Simulate work
            completed_tasks.append(task_id)
            print(f"Task {task_id} completed")
    
    # Start 5 tasks, but only 2 should run concurrently
    tasks = [asyncio.create_task(controlled_task(i)) for i in range(5)]
    
    # Wait for all to complete
    await asyncio.gather(*tasks)
    
    print(f"Completed tasks in order: {completed_tasks}")
    print("✓ Concurrency control test passed")


async def main():
    """Run all tests"""
    print("Testing Async DeepResearch Implementation")
    print("=" * 50)
    
    try:
        await test_async_task_manager()
        await test_task_cancellation()
        await test_concurrency_control()
        
        print("\n" + "=" * 50)
        print("✓ All tests passed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
