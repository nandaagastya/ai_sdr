"""Explicit, reviewable backfill only. Runtime code never matches descriptions."""
import json
import click
from app.models import db, Task, WorkflowTask, RecordedReply, Activity, Meeting, CallOutcome
from app.agents.replies import NEXT


def candidates():
    linked = {value for value, in db.session.query(WorkflowTask.task_id)}
    tasks = [task for task in Task.query.all() if task.id not in linked]
    proposals = {task.id: set() for task in tasks}
    meetings = {meeting.task_id: meeting.reply_id for meeting in Meeting.query.all()}
    replies = db.session.query(RecordedReply, Activity).join(Activity, Activity.id == RecordedReply.activity_id).all()
    outcomes = {record.reply_id: record for record in CallOutcome.query.all()}
    for task in tasks:
        if task.id in meetings:
            proposals[task.id].add((meetings[task.id], 'meeting'))
            continue
        for reply, activity in replies:
            if activity.account_id != task.account_id:
                continue
            try:
                source = json.loads(activity.summary)
                expected = f'Review {reply.outcome.replace("_"," ")} reply #{activity.id} from {source["sender"]}. {NEXT[reply.outcome]}'[:500]
            except (ValueError, KeyError, TypeError):
                continue
            descriptions = {expected: 'reply_review',
                f'Review call brief for reply #{activity.id} before scheduling.': 'brief_review',
                f'Review canceled meeting for reply #{activity.id}; decide next step.': 'cancellation'}
            if task.description in descriptions:
                proposals[task.id].add((activity.id, descriptions[task.description]))
            outcome = outcomes.get(activity.id)
            if outcome and outcome.outcome == 'follow_up' and task.description == outcome.next_step and task.due_at == outcome.follow_up_at:
                proposals[task.id].add((activity.id, 'follow_up'))
    # Multiple tasks for one source/kind are also ambiguous: never pick the first.
    counts = {}
    for choices in proposals.values():
        for choice in choices:
            counts[choice] = counts.get(choice, 0) + 1
    return {task_id: list(choices)[0] if len(choices) == 1 and counts[next(iter(choices))] == 1 else None
            for task_id, choices in proposals.items()}


def apply_selected(task_ids):
    plan = candidates()
    try:
        for task_id in task_ids:
            if db.session.get(WorkflowTask, task_id):
                continue
            if not plan.get(task_id):
                raise ValueError(f'Task {task_id} is unmatched or ambiguous. No links were changed.')
            reply_id, kind = plan[task_id]
            db.session.add(WorkflowTask(task_id=task_id, reply_id=reply_id, kind=kind))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def register(app):
    @app.cli.command('link-legacy-tasks')
    @click.option('--task-id', multiple=True, type=int, help='Explicitly reviewed task IDs to link. Omit for a read-only plan.')
    def link_legacy_tasks(task_id):
        if task_id:
            try:
                apply_selected(task_id)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
            click.echo(f'Linked {len(set(task_id))} selected task IDs (existing links preserved).')
        else:
            for identifier, proposal in candidates().items():
                click.echo(f'Task {identifier}: ' + (f'reply {proposal[0]}, {proposal[1]}' if proposal else 'unmatched or ambiguous; left unchanged'))
            click.echo('Read-only plan. Review source records before passing explicit --task-id values.')
