"""Conservative reply suggestions, versioned and independent of inbox access."""
import re

VERSION = 'reply-rules-v1'
RULES = {
    'unsubscribe': [r'\bunsubscribe\b', r'\bremove me\b', r'\bstop (?:emailing|contacting|sending)\b', r"\b(?:do not|don't) (?:email|contact) me\b"],
    'not_interested': [r'\bnot interested\b', r'\bno thanks\b', r'\bnot a fit\b'],
    'out_of_office': [r'\bout of (?:the )?office\b', r'\bon (?:vacation|leave)\b', r'\bautomatic reply\b'],
    'referral': [r'\b(?:please )?(?:contact|speak (?:to|with)|reach out to)\b', r'\bforwarded (?:this|your)\b'],
    'interested': [r'\b(?:i am|i’m|i\x27m|we are|we’re|we\x27re) interested\b', r'\blet[’\x27]s (?:talk|schedule|meet)\b', r'\bsend (?:me |us )?more (?:information|details)\b'],
}
NEXT = {
    'unsubscribe':'Stop outreach; verify the sender and thread before recording the opt-out.',
    'not_interested':'Stop follow-ups and review the response.',
    'out_of_office':'Hold follow-ups and check the return date manually.',
    'referral':'Review the referred person; do not assume permission to contact them.',
    'interested':'Review the reply and ask for missing qualification details.',
    'needs_review':'Read the reply manually; do not advance or disqualify the contact.',
}


def classify_reply(body):
    if not isinstance(body,str) or not body.strip() or len(body)>10000:
        raise ValueError('Paste a reply between 1 and 10,000 characters.')
    lines=[]
    for line in body.splitlines():
        if re.match(r'^\s*(?:On .+wrote:|From:|-----Original Message-----|--\s*$)',line,re.I):
            break
        if not line.lstrip().startswith('>'):
            lines.append(line)
    current='\n'.join(lines).strip()
    evidence=[]
    for category,patterns in RULES.items():
        for pattern in patterns:
            match=re.search(pattern,current,re.I)
            if match:
                evidence.append({'category':category,'text':match.group(0)})
                break
    categories={item['category'] for item in evidence}
    # Negation, conditionals and mixed intent cannot safely drive automation.
    uncertain=bool(re.search(r'\b(?:if|unless|might|maybe|not|never|don’t|don\x27t)\b',current,re.I))
    category=next(iter(categories)) if len(categories)==1 else 'needs_review'
    if uncertain and category not in {'unsubscribe','not_interested'}:
        category='needs_review'
    return {'version':VERSION,'category':category,'evidence':evidence,
            'next_step':('Hold outreach and review the possible opt-out before any further contact.' if 'unsubscribe' in categories and category == 'needs_review' else NEXT[category]),'needs_review':True,
            'analyzed_text':current,'history_removed':current!=body.strip(),
            'qualification':{'budget':'Unknown','authority':'Unknown','need':'Unknown','timing':'Unknown'}}
