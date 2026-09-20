"""Manual confirmation of an externally agreed time; no calendar calls."""
from datetime import datetime, timezone
from app.models import db, CallBrief, RecordedReply, Contact, Meeting, Task, OutreachStop
from app.services.statuses import advance_contact


def confirm_meeting(reply_id, when, note):
    try: start=datetime.fromisoformat(when.replace('Z','+00:00'))
    except (ValueError,AttributeError): raise ValueError('Enter an ISO date/time with timezone, for example 2026-10-20T14:00:00-04:00.') from None
    if start.tzinfo is None:raise ValueError('Include a timezone offset.')
    start=start.astimezone(timezone.utc).replace(tzinfo=None)
    if not isinstance(note,str) or not note.strip() or len(note)>1000:raise ValueError('Add a confirmation source note up to 1,000 characters.')
    note=note.strip()
    previous=db.session.get(Meeting,reply_id)
    if previous:
        if previous.starts_at==start and previous.confirmation_note==note:return previous
        raise ValueError('A meeting is already recorded. Rescheduling is not yet supported.')
    if start<=datetime.now(timezone.utc).replace(tzinfo=None):raise ValueError('Choose a future agreed time.')
    brief=db.session.get(CallBrief,reply_id)
    record=RecordedReply.query.filter_by(activity_id=reply_id).first()
    if brief is None or record is None:raise ValueError('Prepare the call brief first.')
    contact=db.session.get(Contact,record.contact_id)
    stop=db.session.get(OutreachStop,(contact.email or '').strip().casefold())
    if stop and stop.active and stop.reason in {'unsubscribe','bounced'}:raise ValueError('Contact has an unsubscribe or bounce restriction.')
    try:
        from app.services.workflow_tasks import create_task
        task=create_task(reply_id, 'meeting',
            f'Attend manually confirmed call with {contact.email}; brief for reply #{reply_id}.', start)
        meeting=Meeting(reply_id=reply_id,starts_at=start,task_id=task.id,confirmation_note=note)
        db.session.add(meeting);db.session.flush()
        advance_contact(contact.id,'call_prepped','booked',f'manual meeting confirmation for reply {reply_id}')
        db.session.commit();return meeting
    except Exception:db.session.rollback();raise


def meeting_changes(reply_id):
    from app.models import MeetingChange
    return MeetingChange.query.filter_by(reply_id=reply_id).order_by(MeetingChange.revision.desc()).all()


def change_meeting(reply_id, revision, action, when, note):
    import json
    from app.models import MeetingChange, Activity
    if type(revision) is not int or revision<0 or action not in {'reschedule','cancel'}:
        raise ValueError('Invalid meeting change.')
    if not isinstance(note,str) or not note.strip() or len(note)>1000:
        raise ValueError('Add a source or cancellation note up to 1,000 characters.')
    meeting=db.session.get(Meeting,reply_id)
    if meeting is None:raise ValueError('Meeting not found.')
    history=meeting_changes(reply_id)
    if revision!=(history[0].revision if history else 0):raise ValueError('Meeting changed. Reload before continuing.')
    if history and history[0].action=='cancel':raise ValueError('Meeting is canceled. Rebooking is not yet supported.')
    record=RecordedReply.query.filter_by(activity_id=reply_id).one()
    contact=db.session.get(Contact,record.contact_id)
    task=db.session.get(Task,meeting.task_id)
    if task.status!='open' or contact.pipeline_stage!='booked':raise ValueError('Only an open call for a booked contact can be changed.')
    new_time=meeting.starts_at
    if action=='reschedule':
        try:new_time=datetime.fromisoformat(when.replace('Z','+00:00'))
        except (ValueError,AttributeError):raise ValueError('Enter a valid time with timezone.') from None
        if new_time.tzinfo is None:raise ValueError('Include a timezone offset.')
        new_time=new_time.astimezone(timezone.utc).replace(tzinfo=None)
        if new_time<=datetime.now(timezone.utc).replace(tzinfo=None):raise ValueError('Choose a future agreed time.')
        stop=db.session.get(OutreachStop,(contact.email or '').strip().casefold())
        if stop and stop.active and stop.reason in {'unsubscribe','bounced'}:raise ValueError('Contact has an unsubscribe or bounce restriction.')
    try:
        detail={'previous_time':meeting.starts_at.isoformat()+'Z','previous_note':meeting.confirmation_note,
                'new_time':new_time.isoformat()+'Z' if action=='reschedule' else None,'note':note.strip()}
        db.session.add(MeetingChange(reply_id=reply_id,revision=revision+1,action=action,detail=json.dumps(detail)))
        db.session.flush()  # Unique revision rejects concurrent/stale changes atomically.
        if action=='reschedule':
            meeting.starts_at=new_time;meeting.confirmation_note=note.strip();task.due_at=new_time
        else:
            task.status='skipped'
            contact.pipeline_stage='needs_review'
            from app.services.workflow_tasks import create_task
            create_task(reply_id, 'cancellation', f'Review canceled meeting for reply #{reply_id}; decide next step.')
        db.session.add(Activity(account_id=contact.account_id,contact_id=contact.id,activity_type='meeting_'+action,channel='internal',summary=json.dumps(detail)))
        db.session.commit()
    except Exception:db.session.rollback();raise
