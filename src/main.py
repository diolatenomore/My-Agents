from flask import Flask, request, jsonify
import uuid

from scheduler.task_manager import TaskManager

app = Flask(__name__)

# 创建全局 task_manager 实例
task_manager = TaskManager()
task_manager.run()

@app.route('/api/tasks', methods=['POST'])
def create_task():
    """创建新任务"""
    try:
        data = request.json
        priority = data.get('priority', 1)
        task_type = data.get('type', 'thread')
        config = data.get('config', {})

        # 转换任务类型
        execution_type = ExecutionType.THREAD if task_type == 'thread' else ExecutionType.COROUTINE

        # 后端生成task_id
        task_id = str(uuid.uuid4())

        # 创建任务
        task = Task(
            task_id=task_id,
            priority=priority,
            config=config,
            type=execution_type
        )

        # 提交任务
        task_manager.enqueue(task)

        return jsonify({
            'task_id': task_id,
            'message': f'任务 {task_id} 已提交'
        }), 201
    except Exception as e:
        return jsonify({
            'message': f'创建任务失败: {str(e)}'
        }), 400


@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        status = task_manager.get_task_status(task_id)
        result = task_manager.get_result(task_id)

        return jsonify({
            'task_id': task_id,
            'status': str(status),
            'result': result
        }), 200
    except Exception as e:
        return jsonify({
            'message': f'获取任务状态失败: {str(e)}'
        }), 400


@app.route('/api/tasks/<task_id>/pause', methods=['POST'])
def pause_task(task_id):
    """暂停任务"""
    try:
        task_manager.pause_task(task_id)
        return jsonify({
            'task_id': task_id,
            'message': f'任务 {task_id} 已暂停'
        }), 200
    except Exception as e:
        return jsonify({
            'message': f'暂停任务失败: {str(e)}'
        }), 400


@app.route('/api/tasks/<task_id>/resume', methods=['POST'])
def resume_task(task_id):
    """恢复任务"""
    try:
        task_manager.resume_task(task_id)
        return jsonify({
            'task_id': task_id,
            'message': f'任务 {task_id} 已恢复'
        }), 200
    except Exception as e:
        return jsonify({
            'message': f'恢复任务失败: {str(e)}'
        }), 400


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    """删除任务"""
    try:
        task_manager.delete_task(task_id)
        return jsonify({
            'task_id': task_id,
            'message': f'任务 {task_id} 已删除'
        }), 200
    except Exception as e:
        return jsonify({
            'message': f'删除任务失败: {str(e)}'
        }), 400


@app.route('/api/tasks/<task_id>/priority', methods=['PUT'])
def update_task_priority(task_id):
    """更新任务优先级"""
    try:
        data = request.json
        priority = data.get('priority')
        if priority is None:
            return jsonify({
                'message': '优先级不能为空'
            }), 400

        task_manager.change_priority(task_id, priority)
        return jsonify({
            'task_id': task_id,
            'message': f'任务 {task_id} 优先级已更新为 {priority}'
        }), 200
    except Exception as e:
        return jsonify({
            'message': f'更新任务优先级失败: {str(e)}'
        }), 400


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取系统状态"""
    try:
        # 简单统计信息
        stats = {
            'running': task_manager.running,
            'max_workers': task_manager.max_workers,
            'pending_tasks': len(task_manager.pending_queue),
            'paused_tasks': len(task_manager.paused_queue),
            'active_workers': len(task_manager.workers)
        }
        return jsonify({
            'stats': stats
        }), 200
    except Exception as e:
        return jsonify({
            'message': f'获取系统状态失败: {str(e)}'
        }), 400


if __name__ == '__main__':
    app.run(host='localhost', port=8000, debug=False)
