"""Human-confirmed call completion; no CRM or messaging side effects."""
import json
from datetime import datetime,timezone
from app.models import db,Meeting,CallOutcome,RecordedReply,Contact,Task,Activity
from app.agents.booking import meeting_changes
from app.services.statuses import advance_contact


def log_call(reply_id,outcome,notes,next_step,when):
    if outcome not in {'follow_up','won','lost'}:raise ValueError('Choose a call outcome.')
    if not isinstance(notes,str) or not notes.strip() or len(notes)>4000:raise ValueError('Add call notes up to 4,000 characters.')
    if not isinstance(next_step,str) or len(next_step)>500:raise ValueError('Next step must be at most 500 characters.')
    notes=notes.strip();next_step=next_step.strip();due=None
    if outcome=='follow_up':
        if not next_step:raise ValueError('Describe the follow-up task.')
        try:due=datetime.fromisoformat(when.replace('Z','+00:00'))
        except (ValueError,AttributeError):raise ValueError('Provide a follow-up time with timezone.') from None
        if due.tzinfo is None:raise ValueError('Include the follow-up timezone.')
        due=due.astimezone(timezone.utc).replace(tzinfo=None)
    elif when or next_step:
        raise ValueError('Use follow-up outcome to create a next-step task; clear next-step fields for won or lost.')
    old=db.session.get(CallOutcome,reply_id)
    if old:
        if (old.outcome,old.notes,old.next_step,old.follow_up_at)==(outcome,notes,next_step,due):return old
        raise ValueError('An outcome is already recorded. Corrections require a separate review workflow.')
    if due and due<=datetime.now(timezone.utc).replace(tzinfo=None):raise ValueError('Follow-up time must be in the future.')
    meeting=db.session.get(Meeting,reply_id)
    changes=meeting_changes(reply_id)
    if not meeting or (changes and changes[0].action=='cancel'):raise ValueError('An active recorded meeting is required.')
    if meeting.starts_at>datetime.now(timezone.utc).replace(tzinfo=None):raise ValueError('The recorded call time has not arrived yet.')
    record=RecordedReply.query.filter_by(activity_id=reply_id).one()
    contact=db.session.get(Contact,record.contact_id)
    task=db.session.get(Task,meeting.task_id)
    if task.status!='open':raise ValueError('Call task is not open. Review its history before logging.')
    try:
        result=CallOutcome(reply_id=reply_id,outcome=outcome,notes=notes,next_step=next_step,follow_up_at=due)
        db.session.add(result);db.session.flush()
        advance_contact(contact.id,'booked','called',f'human call completion for reply {reply_id}')
        advance_contact(contact.id,'called','logged',f'call outcome for reply {reply_id}')
        task.status='done'
        if due:
            from app.services.workflow_tasks import create_task
            create_task(reply_id, 'follow_up', next_step, due)
        db.session.add(Activity(account_id=contact.account_id,contact_id=contact.id,activity_type='call',channel='call',summary=json.dumps({'reply_id':reply_id,'outcome':outcome,'notes':notes,'next_step':next_step,'source':'manual completion'})))
        db.session.commit();return result
    except Exception:db.session.rollback();raise
