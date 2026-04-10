import heapq
import threading
import time
import asyncio
from typing import Optional, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor

from config import MAX_WORKERS, CHECKPOINT_DB_PATH
from models.task import Task, TaskStatus, ExecutionType, Priority
from scheduler.worker import BaseWorker, AsyncBaseWorker
from utils.common import logger



class TaskManager:
    """
    中间人/调度器
    管理任务队列、Worker 生命周期、资源调度
    """

    def __init__(self):
        self.max_workers = MAX_WORKERS
        self.db_path = CHECKPOINT_DB_PATH

        # 优先队列
        self.pending_queue: List[Task] = []  # 待执行的任务队列
        self.paused_queue: List[Task] = []   # 已暂停的任务队列
        self.queue_lock = threading.Lock()

        # Worker 管理表：task_id -> Worker
        self.workers: Dict[str, BaseWorker] = {}
        self.worker_lock = threading.Lock()

        # 结果字典：task_id -> result
        self.results: Dict[str, Any] = {}
        self.result_lock = threading.Lock()

        # 线程池执行器
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

        # 调度器状态
        self.running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        
        # 事件循环
        self.event_loop = None
        self.event_loop_thread = None
        self._start_event_loop()

    def _start_event_loop(self):
        """启动事件循环线程"""
        def run_event_loop():
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            try:
                self.event_loop.run_forever()
            finally:
                self.event_loop.close()
        
        self.event_loop_thread = threading.Thread(target=run_event_loop)
        self.event_loop_thread.daemon = True
        self.event_loop_thread.start()
        # 等待事件循环初始化完成
        while self.event_loop is None:
            time.sleep(0.1)

    def enqueue(self, task: Task, preemptive: bool = False):
        """
        提交任务
        
        Args:
            task (Task): 任务对象
            preemptive (bool, optional): 是否启用抢占式调度。默认为False
        """
        # 加入待执行队列
        with self.queue_lock:
            heapq.heappush(self.pending_queue, task)
        logger.info(f"[TaskManager] 任务 {task.task_id} 已提交，优先级: {task.priority})")
        # print(f"[TaskManager] 任务 {task.task_id} 已提交，优先级: {task.priority})")
        
        # 执行抢占式调度
        if preemptive:
            self._perform_preemption()

    def dequeue(self):
        """
        从待执行队列中取出任务
        """
        with self.queue_lock:
            if not self.pending_queue:
                return None
            task = heapq.heappop(self.pending_queue)
            logger.info(f"[TaskManager] 任务 {task.task_id} 已从待执行队列取出，优先级: {task.priority})")
            # print(f"[TaskManager] 任务 {task.task_id} 已从待执行队列取出，优先级: {task.priority})")
            return task

    def set_result(self, task_id: str, result: Any):
        """
        设置任务结果
        """
        with self.result_lock:
            self.results[task_id] = result
        # 任务完成后清理worker
        with self.worker_lock:
            if task_id in self.workers:
                del self.workers[task_id]
                logger.info(f"[TaskManager] 任务 {task_id} 已完成，worker已清理")
                # print(f"[TaskManager] 任务 {task_id} 已完成，worker已清理")
        
    def get_result(self, task_id: str):
        """
        获取任务结果
        """
        with self.result_lock:
            return self.results.get(task_id)

    def get_task_status(self, task_id: str):
        """获取任务状态"""
        # 首先检查任务是否在执行中
        with self.worker_lock:
            worker = self.workers.get(task_id)
            if worker:
                return worker.task.status
        # 然后检查任务是否在待执行队列中
        with self.queue_lock:
            for task in self.pending_queue:
                if task.task_id == task_id:
                    return task.status
            # 检查任务是否在暂停队列中
            for task in self.paused_queue:
                if task.task_id == task_id:
                    return task.status
        # 任务不存在
        # TODO 还可能是已完成的任务
        return None

    def pause_task(self, task_id):
        """
        暂停任务
        """
        with self.worker_lock:
            worker = self.workers.get(task_id)
            if worker:
                worker.pause()
                task = worker.task
                # 从workers中移除
                del self.workers[task_id]
                # 将任务添加到暂停队列
                with self.queue_lock:
                    heapq.heappush(self.paused_queue, task)
                logger.info(f"[TaskManager] 任务 {task_id} 已暂停并移至暂停队列")
                # print(f"[TaskManager] 任务 {task_id} 已暂停并移至暂停队列")
                return f"任务 {task_id} 已暂停并移至暂停队列"

        # 若不在执行中，检查是否在待执行队列
        with self.queue_lock:
            for i, task in enumerate(self.pending_queue):
                if task.task_id == task_id:
                    # 从待执行队列移除
                    self.pending_queue.pop(i)
                    heapq.heapify(self.pending_queue)
                    # 更新状态并加入暂停队列
                    task.status = TaskStatus.PAUSED
                    heapq.heappush(self.paused_queue, task)
                    logger.info(f"[TaskManager] 任务 {task_id} 已从待执行队列暂停")
                    # print(f"[TaskManager] 任务 {task_id} 已从待执行队列暂停")
                    return f"任务 {task_id} 已暂停并移至暂停队列"

        logger.info(f"[TaskManager] 任务 {task_id} 不存在或未执行/待执行")
        # print(f"[TaskManager] 任务 {task_id} 不存在或未在执行/待执行")
        return f"任务 {task_id} 不存在或未执行/待执行"

    def resume_task(self, task_id, preemptive: bool = False):
        """
        恢复暂停任务
        
        Args:
            task_id (str): 任务ID
            preemptive (bool, optional): 是否启用抢占式调度。默认为False
        """
        # 从暂停队列中找到并移除任务
        with self.queue_lock:
            task_found = None
            task_index = -1
            for i, task in enumerate(self.paused_queue):
                if task.task_id == task_id:
                    task_found = task
                    task_index = i
                    break
            
            if task_found:
                # 从暂停队列中移除
                self.paused_queue.pop(task_index)
                # 重新堆化暂停队列
                heapq.heapify(self.paused_queue)
                # 更新任务状态
                task_found.status = TaskStatus.PENDING
                task_found.is_resume = True
                # 将任务添加到待执行队列
                heapq.heappush(self.pending_queue, task_found)
                logger.info(f"[TaskManager] 任务 {task_id} 已恢复并移至待执行队列")
                # print(f"[TaskManager] 任务 {task_id} 已恢复并移至待执行队列")
            else:
                logger.info(f"[TaskManager] 任务 {task_id} 不存在或未暂停")
                # print(f"[TaskManager] 任务 {task_id} 不存在或未暂停")

        # 实现抢占式逻辑（在锁外部执行，因为锁不是可重入的）
        if task_found:
            if preemptive:
                self._perform_preemption()
            return f"任务 {task_id} 已恢复并移至待执行队列"
        else:
            return f"任务 {task_id} 不存在或未暂停"

    def delete_task(self, task_id):
        """删除任务"""
        # 如果任务已完成则清理结果
        with self.result_lock:
            if task_id in self.results:
                del self.results[task_id]
                logger.info(f"[TaskManager] 任务 {task_id} 的结果已清理")
                # print(f"[TaskManager] 任务 {task_id} 的结果已清理")
                return f"任务 {task_id} 已完成，结果已清理"

        task_found = False
        result = None
        # 首先检查任务是否在执行中
        with self.worker_lock:
            if task_id in self.workers:
                worker = self.workers[task_id]
                worker.cancel()
                del self.workers[task_id]

                result = f"任务 {task_id} 正在执行，已取消并清理worker"
                task_found = True

                logger.info(f"[TaskManager] 任务 {task_id} 正在执行，已取消并清理worker")
                # print(f"[TaskManager] 任务 {task_id} 正在执行，已取消并清理worker")

        # 检查任务是否在待执行队列中
        if not task_found:
            with self.queue_lock:
                # 检查待执行队列
                for i, task in enumerate(self.pending_queue):
                    if task.task_id == task_id:
                        self.pending_queue.pop(i)
                        heapq.heapify(self.pending_queue)

                        task_found = True
                        result = f"任务 {task_id} 已从待执行队列中删除"

                        logger.info(f"[TaskManager] 任务 {task_id} 已从待执行队列中删除")
                        # print(f"[TaskManager] 任务 {task_id} 已从待执行队列中删除")
            
        # 检查任务是否在暂停队列中
        if not task_found:
            for i, task in enumerate(self.paused_queue):
                if task.task_id == task_id:
                    self.paused_queue.pop(i)
                    heapq.heapify(self.paused_queue)

                    task_found = True
                    result = f"任务 {task_id} 已从暂停队列中删除"

                    logger.info(f"[TaskManager] 任务 {task_id} 已从暂停队列中删除")
                    # print(f"[TaskManager] 任务 {task_id} 已从暂停队列中删除")

        if task_found:
            return result
        else:
            return f"任务 {task_id} 不存在"



    def change_priority(self, task_id: str, priority: Priority, preemptive: bool = False):
        """
        改变任务优先级
        
        Args:
            task_id (str): 任务ID
            priority (int): 新的优先级值（值越小优先级越高）
            preemptive (bool, optional): 是否启用抢占式调度。默认为False
        
        执行流程：
        1. 获取任务状态
        2. 检查任务是否存在
        3. 检查任务是否已完成/取消/错误，若是则返回
        4. 根据任务状态修改优先级：
           - RUNNING: 直接更新执行中任务的优先级
           - PENDING: 从待执行队列移除，更新优先级后重新加入
           - PAUSED: 从暂停队列移除，更新优先级后重新加入
        5. 判断是否启用抢占式调度
        """
        # 复用 get_task_status 方法获取任务状态
        status = self.get_task_status(task_id)
        
        if status is None:
            logger.info(f"[TaskManager] 任务 {task_id} 不存在")
            # print(f"[TaskManager] 任务 {task_id} 不存在")
            return f"任务 {task_id} 不存在"
        
        if status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.ERROR):
            logger.info(f"[TaskManager] 任务 {task_id} 已完成/取消/错误，无法修改优先级")
            # print(f"[TaskManager] 任务 {task_id} 已完成/取消/错误，无法修改优先级")
            return f"任务 {task_id} 已完成/取消/错误，无法修改优先级"
        
        # 根据任务状态决定如何修改优先级
        # 任务正在执行
        if status == TaskStatus.RUNNING:
            with self.worker_lock:
                worker = self.workers.get(task_id)
                if worker:
                    # 更新任务优先级
                    worker.task.priority = priority
                    logger.info(f"[TaskManager] 任务 {task_id} 优先级已修改为 {priority}")
                    # print(f"[TaskManager] 任务 {task_id} 优先级已修改为 {priority}")
        
        # 任务在待执行队列
        elif status == TaskStatus.PENDING:    
            with self.queue_lock:
                task_found = None
                task_index = -1
                for i, task in enumerate(self.pending_queue):
                    if task.task_id == task_id:
                        task_found = task
                        task_index = i
                        break
                
                if task_found:
                    # 从队列中移除
                    self.pending_queue.pop(task_index)
                    heapq.heapify(self.pending_queue)
                    
                    # 更新优先级
                    task_found.priority = priority
                    
                    # 重新加入队列
                    heapq.heappush(self.pending_queue, task_found)
                    logger.info(f"[TaskManager] 任务 {task_id} 优先级已修改为 {priority}")
                    # print(f"[TaskManager] 任务 {task_id} 优先级已修改为 {priority}")
        
        # 任务在暂停队列
        elif status == TaskStatus.PAUSED:    
            with self.queue_lock:
                task_found = None
                task_index = -1
                for i, task in enumerate(self.paused_queue):
                    if task.task_id == task_id:
                        task_found = task
                        task_index = i
                        break
                
                if task_found:
                    # 从队列中移除
                    self.paused_queue.pop(task_index)
                    heapq.heapify(self.paused_queue)
                    
                    # 更新优先级
                    task_found.priority = priority
                    
                    # 重新加入队列
                    heapq.heappush(self.paused_queue, task_found)
                    logger.info(f"[TaskManager] 任务 {task_id} 优先级已修改为 {priority}")
                    # print(f"[TaskManager] 任务 {task_id} 优先级已修改为 {priority}")
        
        # 执行抢占式调度
        if preemptive:
            self._perform_preemption()

        return f"任务 {task_id} 优先级已修改为 {priority}"
    
    def _perform_preemption(self):
        """
        执行抢占式调度
        抢占本质上是检查当前执行任务的最低优先级是否低于待执行队列中的最高优先级，这样就无需关注是哪个任务的优先级被调整
        
        执行流程：
            - 检查待执行队列是否有任务
            - 检查worker数是否已满
            - 找出当前执行中优先级最低的任务
            - 比较待执行队列中最高优先级任务与当前最低优先级任务
            - 若待执行任务优先级更高，则执行抢占
        """
        with self.queue_lock:
            # 检查待执行队列是否为空
            if not self.pending_queue:
                # 没有待执行任务，不需要抢占
                return
            # 获取待执行队列中优先级最高的任务（堆顶元素）
            highest_priority_task = self.pending_queue[0]

        with self.worker_lock:
            # 检查当前worker数是否已满
            if len(self.workers) < self.max_workers:
                # 还有空闲worker槽位，不需要抢占
                return
            # 找出当前执行中优先级最低的任务
            lowest_priority_worker = None
            lowest_priority = float('-inf')
            
            for worker in self.workers.values():
                task_priority = worker.task.priority
                if task_priority > lowest_priority:  # 优先级值越大，优先级越低
                    lowest_priority = task_priority
                    lowest_priority_worker = worker
            
            # 比较待执行任务和当前最低优先级任务的优先级
            if lowest_priority_worker and highest_priority_task.priority < lowest_priority:
                # 待执行任务优先级更高，执行抢占
                logger.info(f"[TaskManager] 执行抢占：暂停优先级较低的任务 {lowest_priority_worker.task.task_id}，执行优先级更高的任务 {highest_priority_task.task_id}")
                # print(f"[TaskManager] 执行抢占：暂停优先级较低的任务 {lowest_priority_worker.task.task_id}，执行优先级更高的任务 {highest_priority_task.task_id}")

                # 暂停当前最低优先级的任务
                task_id_to_pause = lowest_priority_worker.task.task_id
                
                # 从workers中移除
                del self.workers[task_id_to_pause]
                
                # 更新任务状态为PENDING
                lowest_priority_worker.task.status = TaskStatus.PENDING
                lowest_priority_worker.task.is_resume = True
                
                # 将任务添加到待执行队列
                with self.queue_lock:
                    heapq.heappush(self.pending_queue, lowest_priority_worker.task)
                logger.info(f"[TaskManager] 任务 {task_id_to_pause} 已暂停并移至待执行队列")
                # print(f"[TaskManager] 任务 {task_id_to_pause} 已暂停并移至待执行队列")

    def run(self):
        """启动调度器"""
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        logger.info("[TaskManager] 调度器已启动")
        # print("[TaskManager] 调度器已启动")

    def _scheduler_loop(self):
        """调度器主循环"""
        while self.running:
            # 检查是否有空闲worker槽位
            with self.worker_lock:
                if len(self.workers) < self.max_workers:
                    # 检查是否有待执行的任务
                    task = self.dequeue()
                    if task:
                        worker = AsyncBaseWorker(task, self)
                        self.workers[task.task_id] = worker
                        # 将协程提交到全局事件循环
                        future = asyncio.run_coroutine_threadsafe(worker.run(), self.event_loop)
                        # 保存 asyncio.Task 引用
                        worker.set_running_task(future)
                        logger.info(f"[TaskManager] 任务 {task.task_id} 已分配给协程worker")
                        # print(f"[TaskManager] 任务 {task.task_id} 已分配给协程worker")
            # 短暂休眠，避免CPU占用过高
            time.sleep(0.1)

    def close(self):
        """关闭调度器"""
        logger.info("[TaskManager] 调度器已关闭")
        # print("[TaskManager] 调度器已关闭")
        self.running = False
        # 暂停所有正在运行的任务
        with self.worker_lock:
            for worker in self.workers.values():
                worker.pause()
        # 关闭线程池
        self.executor.shutdown(wait=True)
        # 关闭事件循环
        if self.event_loop:
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        if self.event_loop_thread:
            self.event_loop_thread.join(timeout=1)