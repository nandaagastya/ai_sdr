"""Inspectable company-fit rules; missing facts never earn target-fit points."""
import re
from urllib.parse import urlsplit

VERSION = 'icp-v2'


def assess(name=None, industry=None, employees=None, location=None, domain=None):
    reasons, score = [], 0
    count = None
    if not isinstance(employees, bool):
        try:
            if str(employees).isdigit() and 0 < int(employees) <= 100000000:
                count = int(employees)
        except (ValueError, TypeError):
            pass
    size_match = count is not None and 51 <= count <= 500
    score += 40 if size_match else 0
    reasons.append('Employees unknown (+0)' if count is None else f'Employees {count}: {"in" if size_match else "outside"} 51–500 target (+{40 if size_match else 0})')
    # Names alone are not evidence that a company provides Salesforce services.
    vertical = industry.strip().lower() if isinstance(industry, str) else ''
    vertical_match = bool(re.search(r'\bsalesforce\b', vertical) and re.search(r'\b(consulting|consultancy|implementation|implementations|services|integration|integrations)\b', vertical))
    score += 30 if vertical_match else 0
    reasons.append('Salesforce services evidence in industry (+30)' if vertical_match else ('Industry unknown (+0)' if not vertical else 'Industry does not establish Salesforce services (+0)'))
    country = location.strip().casefold() if isinstance(location, str) else ''
    us = country in {'united states', 'united states of america', 'us', 'usa', 'u.s.', 'u.s.a.'}
    score += 20 if us else 0
    reasons.append('US location supplied (+20)' if us else ('Location unknown (+0)' if not country else 'Location not confirmed as US (+0)'))
    valid_domain = False
    if isinstance(domain, str):
        try:
            parsed = urlsplit(domain if '://' in domain else 'https://' + domain)
            host = parsed.hostname or ''
            valid_domain = parsed.scheme in {'http','https'} and '.' in host and not parsed.username and not re.search(r'\s', domain)
        except ValueError:
            pass
    score += 10 if valid_domain else 0
    reasons.append('Company domain supplied; not email verification (+10)' if valid_domain else 'Company domain missing or invalid (+0)')
    if size_match and vertical_match and us:
        status = 'strong_fit'
    elif count is not None and not size_match:
        status = 'low_fit'
    elif count is None or not vertical or not country:
        status = 'unassessed'
    else:
        status = 'possible_fit'
    return score, reasons, status


def apply_quality(account):
    score, reasons, status = assess(account.name, account.industry, account.employee_count,
                                    account.location, account.domain)
    account.icp_fit_score = score
    account.icp_fit_reasons = ' | '.join([VERSION, *reasons])
    account.fit_status = status
