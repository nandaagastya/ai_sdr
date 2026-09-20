"""Read-only next actions with bounded database queries and explicit task links."""
from datetime import datetime
from sqlalchemy.orm import selectinload
from app.models import (db, RecordedReply, Contact, Qualification, CallBrief, Meeting,
                        MeetingChange, CallOutcome, OutreachStop, Task, WorkflowTask)


def next_actions():
    latest = db.session.query(RecordedReply.contact_id,
        db.func.max(RecordedReply.activity_id).label('reply_id')).group_by(RecordedReply.contact_id).subquery()
    last_change = db.session.query(MeetingChange.reply_id,
        db.func.max(MeetingChange.revision).label('revision')).group_by(MeetingChange.reply_id).subquery()
    follow_up = db.session.query(WorkflowTask.reply_id).join(Task, Task.id == WorkflowTask.task_id).filter(
        WorkflowTask.kind == 'follow_up', Task.status == 'open').distinct().subquery()
    query = db.session.query(RecordedReply, Contact, Qualification, CallBrief, Meeting,
        CallOutcome, OutreachStop, MeetingChange.action, follow_up.c.reply_id).join(
        latest, RecordedReply.activity_id == latest.c.reply_id).join(
        Contact, Contact.id == RecordedReply.contact_id).outerjoin(
        Qualification, Qualification.reply_id == RecordedReply.activity_id).outerjoin(
        CallBrief, CallBrief.reply_id == RecordedReply.activity_id).outerjoin(
        Meeting, Meeting.reply_id == RecordedReply.activity_id).outerjoin(
        CallOutcome, CallOutcome.reply_id == RecordedReply.activity_id).outerjoin(
        OutreachStop, OutreachStop.email == db.func.lower(db.func.trim(Contact.email))).outerjoin(
        last_change, last_change.c.reply_id == RecordedReply.activity_id).outerjoin(
        MeetingChange, db.and_(MeetingChange.reply_id == last_change.c.reply_id,
                              MeetingChange.revision == last_change.c.revision)).outerjoin(
        follow_up, follow_up.c.reply_id == RecordedReply.activity_id).options(
        selectinload(Contact.account)).order_by(RecordedReply.activity_id.desc())
    actions = []
    for reply, contact, qualification, brief, meeting, outcome, stop, change, has_follow_up in query:
        base = f'/replies/{reply.activity_id}'
        if stop and stop.active and stop.reason in {'unsubscribe', 'bounced'}:
            label, reason, url = 'Review contact restriction', f'Outreach stopped: {stop.reason}.', base
        elif contact.pipeline_stage == 'needs_review' and change != 'cancel':
            label, reason, url = 'Review reply and next step', 'Contact progress requires human review.', base
        elif outcome:
            if outcome.outcome in {'won', 'lost'} or has_follow_up is None:
                continue
            label, reason, url = 'Review post-call follow-up', 'Call outcome is saved. Check its linked follow-up task.', '/tasks'
        elif change == 'cancel':
            label, reason, url = 'Decide next step after cancellation', 'Meeting canceled; outreach stays stopped.', base + '/call-brief'
        elif meeting:
            label = 'Log call outcome' if meeting.starts_at <= datetime.utcnow() else 'Review upcoming call'
            reason, url = f'Meeting time: {meeting.starts_at:%Y-%m-%d %H:%M} UTC.', base + '/call-brief'
        elif brief and contact.pipeline_stage == 'call_prepped':
            label, reason, url = 'Record agreed meeting', 'Call brief is ready. No calendar invitation has been created.', base + '/call-brief'
        elif qualification and qualification.qualified and contact.pipeline_stage == 'qualified':
            label, reason, url = 'Prepare call brief', 'Qualification evidence is confirmed.', base
        elif reply.outcome == 'interested' and contact.pipeline_stage == 'replied':
            label, reason, url = 'Complete qualification', 'Interest alone does not qualify the prospect.', base
        else:
            label, reason, url = 'Review reply and next step', 'Human review is needed before progressing.', base
        actions.append({'contact': contact, 'label': label, 'reason': reason, 'url': url})
    return actions


def task_contexts(tasks):
    """Batch read. Unlinked historical/manual tasks remain visible, never guessed."""
    ids = [task.id for task in tasks]
    results = dict.fromkeys(ids)
    for offset in range(0, len(ids), 500):
        rows = db.session.query(WorkflowTask, Qualification.qualified, Meeting.reply_id, CallOutcome.reply_id).outerjoin(
            Qualification, Qualification.reply_id == WorkflowTask.reply_id).outerjoin(
            Meeting, Meeting.reply_id == WorkflowTask.reply_id).outerjoin(
            CallOutcome, CallOutcome.reply_id == WorkflowTask.reply_id).filter(
            WorkflowTask.task_id.in_(ids[offset:offset + 500])).all()
        for link, qualified, meeting, outcome in rows:
            brief_page = link.kind in {'brief_review', 'meeting', 'cancellation', 'follow_up'}
            resolved = bool((link.kind == 'reply_review' and qualified)
                or (link.kind == 'brief_review' and meeting is not None)
                or (link.kind == 'meeting' and outcome is not None))
            results[link.task_id] = {'url': f'/replies/{link.reply_id}' + ('/call-brief' if brief_page else ''),
                'label': 'Open call record' if brief_page else 'Open reply', 'resolved': resolved}
    return results


def task_context(task):
    return task_contexts([task])[task.id]
