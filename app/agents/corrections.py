"""Append-only corrections with before/after evidence and atomic task updates."""
import json
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from app.models import (db, Activity, RecordedReply, Qualification, CallOutcome,
                        RecordCorrection, Contact, CallBrief)
from app.agents.qualification import FIELDS
from app.services.eligibility import set_stop
from app.services.workflow_tasks import create_task, linked_tasks


def history(reply_id, entity):
    return RecordCorrection.query.filter_by(reply_id=reply_id, entity=entity).order_by(
        RecordCorrection.revision.desc()).all()


def outcome_snapshot(outcome):
    return {'outcome': outcome.outcome, 'notes': outcome.notes, 'next_step': outcome.next_step,
            'follow_up_at': outcome.follow_up_at.isoformat() + 'Z' if outcome.follow_up_at else None}


def _validate(reply_id, revision, reviewer, reason):
    if type(revision) is not int or revision < 0:
        raise ValueError('Reload the current revision before correcting it.')
    for value, limit, label in [(reviewer, 120, 'Reviewer'), (reason, 1000, 'Correction reason')]:
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'{label} is required and must be at most {limit} characters.')
    record = RecordedReply.query.filter_by(activity_id=reply_id).first()
    if record is None:
        raise ValueError('Saved reply not found.')
    return db.session.get(Contact, record.contact_id)


def _append(reply_id, entity, revision, before, after, reviewer, reason):
    db.session.add(RecordCorrection(reply_id=reply_id, entity=entity, revision=revision,
        reviewer=reviewer.strip(), reason=reason.strip(), before=json.dumps(before), after=json.dumps(after)))
    db.session.flush()


def correct_qualification(reply_id, revision, evidence, keep_qualified, reviewer, reason):
    contact = _validate(reply_id, revision, reviewer, reason)
    current = db.session.get(Qualification, reply_id)
    if not current or not current.qualified or current.revision != revision:
        raise ValueError('Only the current confirmed assessment can be corrected. Reload the reply.')
    if not isinstance(evidence, dict) or set(evidence) != set(FIELDS) or type(keep_qualified) is not bool:
        raise ValueError('Provide all four evidence fields and a qualification decision.')
    if any(not isinstance(v, str) or len(v) > 1500 for v in evidence.values()):
        raise ValueError('Evidence notes must be at most 1,500 characters each.')
    evidence = {k: v.strip() for k, v in evidence.items()}
    if keep_qualified and not all(evidence.values()):
        raise ValueError('Confirmed qualification requires all four evidence notes.')
    before = {'evidence': json.loads(current.evidence), 'qualified': current.qualified}
    after = {'evidence': evidence, 'qualified': keep_qualified}
    if before == after:
        raise ValueError('No changes to save.')
    try:
        changed = db.session.execute(db.update(Qualification).where(
            Qualification.reply_id == reply_id, Qualification.revision == revision,
            Qualification.qualified == True).values(
            evidence=json.dumps(evidence), qualified=keep_qualified, revision=revision + 1))
        if changed.rowcount != 1:
            raise ValueError('Assessment changed. Reload before correcting it.')
        _append(reply_id, 'qualification', revision + 1, before, after, reviewer, reason)
        if not keep_qualified or db.session.get(CallBrief, reply_id):
            # Preserve historical briefs/meetings; a changed source requires explicit review.
            contact.pipeline_stage = 'needs_review'
            if contact.email:
                set_stop(contact.email, 'paused')
            create_task(reply_id, 'correction_review',
                f'Review corrected qualification for reply #{reply_id}; check any existing brief and meeting.')
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError('Assessment changed. Reload before correcting it.') from None
    except Exception:
        db.session.rollback()
        raise


def correct_outcome(reply_id, revision, outcome, notes, next_step, when, reviewer, reason):
    contact = _validate(reply_id, revision, reviewer, reason)
    current = db.session.get(CallOutcome, reply_id)
    prior = history(reply_id, 'call_outcome')
    if current is None or revision != (prior[0].revision if prior else 0):
        raise ValueError('Call outcome changed or is missing. Reload before correcting it.')
    if outcome not in {'follow_up', 'won', 'lost'}:
        raise ValueError('Choose a supported outcome.')
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 4000:
        raise ValueError('Add call notes up to 4,000 characters.')
    if not isinstance(next_step, str) or len(next_step) > 500:
        raise ValueError('Next step must be at most 500 characters.')
    due = None
    if outcome == 'follow_up':
        if not next_step.strip():
            raise ValueError('Describe the follow-up task.')
        try:
            due = datetime.fromisoformat(when.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            raise ValueError('Provide a follow-up time with timezone.') from None
        if due.tzinfo is None:
            raise ValueError('Include a timezone offset.')
        due = due.astimezone(timezone.utc).replace(tzinfo=None)
    elif next_step.strip() or when:
        raise ValueError('Clear follow-up fields for won or lost outcomes.')
    before = outcome_snapshot(current)
    after = {'outcome': outcome, 'notes': notes.strip(), 'next_step': next_step.strip(),
             'follow_up_at': due.isoformat() + 'Z' if due else None}
    if before == after:
        raise ValueError('No changes to save.')
    tasks = linked_tasks(reply_id, 'follow_up')
    open_tasks = [task for task in tasks if task.status == 'open']
    if current.outcome == 'follow_up' and not tasks:
        raise ValueError('This older outcome has no explicit task link. Review and link its task before correcting it.')
    task_changed = (current.outcome, current.next_step, current.follow_up_at) != (outcome, next_step.strip(), due)
    if task_changed and due and due <= datetime.utcnow():
        raise ValueError('A changed follow-up must be in the future.')
    try:
        _append(reply_id, 'call_outcome', revision + 1, before, after, reviewer, reason)
        if task_changed:
            for task in open_tasks:
                task.status = 'skipped'  # Preserve original task and completed history.
            if due:
                create_task(reply_id, 'follow_up', next_step.strip(), due)
        current.outcome, current.notes = outcome, notes.strip()
        current.next_step, current.follow_up_at = next_step.strip(), due
        # Correcting notes/outcome never sends, lifts stops or rewinds contact progress.
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError('Call outcome changed. Reload before correcting it.') from None
    except Exception:
        db.session.rollback()
        raise
