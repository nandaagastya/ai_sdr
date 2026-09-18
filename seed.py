"""
Seed the database with a realistic pipeline so the dashboard has something
to show without needing a live Apollo key. Mirrors the shape of a real
prospecting run: a spread of ICP scores, a few accounts already through
outreach/replied/booked, some open follow-up tasks, and an agent-run
audit trail across the pipeline stages (most stubbed since only
Prospecting is live in this prototype).

Usage: python seed.py
"""
import random
from datetime import datetime, timedelta

from app import create_app
from app.models import db, Account, Contact, Activity, Task, AgentRun

random.seed(42)

ACCOUNTS = [
    # (name, domain, industry, employees, location, stage, score)
    ("Prudent Consulting", "prudentconsulting.com", "Salesforce Consulting", 120, "United States", "booked", 92),
    ("DataSkate.ai", "dataskate.ai", "Salesforce Consulting", 85, "United States", "replied", 88),
    ("IdeaHelix", "ideahelix.com", "CRM Consulting", 210, "United States", "outreach", 81),
    ("Bayforce", "bayforce.com", "Salesforce Consulting", 340, "United States", "outreach", 76),
    ("Gravity Info Solutions", "gravityinfosolutions.com", "IT Consulting", 150, "United States", "qualified", 68),
    ("Meridian CRM Partners", "meridiancrm.com", "Salesforce Consulting", 60, "United States", "qualified", 71),
    ("Northwind Digital", "northwinddigital.com", "Digital Transformation", 95, "United States", "new", 54),
    ("Clearbridge Technology Group", "clearbridgetg.com", "Salesforce Consulting", 480, "United States", "new", 63),
    ("Vantage Point Consulting", "vantagepointconsulting.com", "Business Consulting", 40, "United States", "new", 38),
    ("Silverline Reply Co", "silverlinereply.com", "Salesforce Consulting", 275, "United States", "closed", 84),
]

FIRST_NAMES = ["Jordan", "Alex", "Priya", "Sam", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Drew"]
LAST_NAMES = ["Chen", "Martinez", "Patel", "Nguyen", "Johnson", "Williams", "Brown", "Davis", "Garcia", "Kim"]
TITLES = ["VP of Sales", "Director of RevOps", "Head of Growth", "CEO", "Salesforce Practice Lead", "COO"]


def build():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        accounts_by_name = {}
        for name, domain, industry, employees, location, stage, score in ACCOUNTS:
            domain = domain.replace(".", "-") + ".example"
            reasons = []
            if 51 <= employees <= 500:
                reasons.append(f"employee count {employees} in target range (51-500)")
            if "consulting" in industry.lower() or "salesforce" in industry.lower():
                reasons.append("keyword/industry match on target vertical")
            reasons.append("US-based (or unspecified, treated as pass)")
            reasons.append("has a contactable domain")

            account = Account(
                name=name,
                domain=domain,
                industry=industry,
                employee_count=employees,
                location=location,
                icp_fit_score=score,
                icp_fit_reasons=" | ".join(reasons),
                stage=stage,
                source="demo",
                created_at=datetime.utcnow() - timedelta(days=random.randint(2, 30)),
            )
            db.session.add(account)
            accounts_by_name[name] = account

        db.session.flush()

        for name, account in accounts_by_name.items():
            num_contacts = random.randint(1, 3)
            for i in range(num_contacts):
                first = random.choice(FIRST_NAMES)
                last = random.choice(LAST_NAMES)
                contact = Contact(
                    account_id=account.id,
                    first_name=first,
                    last_name=last,
                    title=random.choice(TITLES),
                    email=f"{first.lower()}.{last.lower()}@{account.domain}",
                    linkedin_url=None,
                    is_decision_maker=(i == 0),
                )
                db.session.add(contact)

            if account.stage in ("outreach", "replied", "booked", "closed"):
                db.session.add(Activity(
                    account_id=account.id,
                    activity_type="email_sent",
                    channel="email",
                    summary=f"Initial outreach sequence sent to {name}.",
                    created_at=account.created_at + timedelta(days=1),
                ))
            if account.stage in ("replied", "booked", "closed"):
                db.session.add(Activity(
                    account_id=account.id,
                    activity_type="reply",
                    channel="email",
                    summary=f"{name} replied expressing interest.",
                    created_at=account.created_at + timedelta(days=3),
                ))
            if account.stage in ("booked", "closed"):
                db.session.add(Activity(
                    account_id=account.id,
                    activity_type="call",
                    channel="phone",
                    summary=f"Discovery call booked with {name} (human-handled).",
                    created_at=account.created_at + timedelta(days=5),
                ))

            if account.stage in ("new", "qualified"):
                db.session.add(Task(
                    account_id=account.id,
                    description=f"Review ICP fit and decide on outreach sequence for {name}",
                    owner="agent",
                    status="open",
                    due_at=datetime.utcnow() + timedelta(days=random.randint(1, 5)),
                ))
            elif account.stage == "outreach":
                db.session.add(Task(
                    account_id=account.id,
                    description=f"Send follow-up #2 to {name} (no reply after 4 days)",
                    owner="agent",
                    status="open",
                    due_at=datetime.utcnow() + timedelta(days=1),
                ))

        # Agent run audit trail — prospecting is live, the rest are stubbed
        # to reflect the target eight-agent shape.
        run_specs = [
            ("prospecting", "success", 10, "Fetched 10 orgs from Apollo, upserted 10 accounts.", 6),
            ("prospecting", "success", 5, "Enrichment pass on 5 shortlisted domains.", 4),
            ("outreach", "success", 4, "[stub] Queued outreach sequences for 4 qualified accounts.", 3),
            ("reply_qualification", "success", 2, "[stub] Classified 2 replies as interested.", 2),
            ("call_prep", "success", 1, "[stub] Generated call brief for Prudent Consulting.", 1),
            ("booking", "success", 1, "[stub] Booking link sent, meeting confirmed.", 1),
        ]
        for agent_name, status, records, detail, days_ago in run_specs:
            started = datetime.utcnow() - timedelta(days=days_ago, hours=random.randint(0, 20))
            db.session.add(AgentRun(
                agent_name=agent_name,
                status=status,
                records_processed=records,
                detail="[DEMO] " + detail,
                started_at=started,
                finished_at=started + timedelta(minutes=random.randint(1, 8)),
            ))

        db.session.commit()
        print(f"Seeded {len(ACCOUNTS)} accounts, contacts, activities, tasks, and {len(run_specs)} agent runs.")


if __name__ == "__main__":
    build()
