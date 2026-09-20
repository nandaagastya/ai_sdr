"""Create workflow tasks in the caller's business transaction."""
from app.models import db, Activity, Task, WorkflowTask


def create_task(reply_id, kind, description, due_at=None):
    source = db.session.get(Activity, reply_id)
    if source is None or source.activity_type != 'reply':
        raise ValueError('A saved reply is required for a workflow task.')
    task = Task(account_id=source.account_id, owner='human', status='open',
                description=description, due_at=due_at)
    db.session.add(task)
    db.session.flush()
    db.session.add(WorkflowTask(task_id=task.id, reply_id=reply_id, kind=kind))
    return task


def linked_tasks(reply_id, kind):
    return Task.query.join(WorkflowTask, WorkflowTask.task_id == Task.id).filter(
        WorkflowTask.reply_id == reply_id, WorkflowTask.kind == kind).order_by(Task.id).all()
