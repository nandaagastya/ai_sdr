"""Bounded public-web reads: pinned public IPs, robots rules, no credentials."""
import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, urljoin, unquote
from urllib.robotparser import RobotFileParser

import certifi
import urllib3

AGENT = 'AISDRResearchBot'
MAX_BODY = 1024 * 1024


def normalize_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError('Provide a valid public website URL.')
    value = value.strip()
    if any(ord(c) < 33 for c in value) or '\\' in value:
        raise ValueError('URLs must not contain spaces or control characters.')
    parsed = urlsplit(value if '://' in value else 'https://' + value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTP or HTTPS URL without login credentials.')
    host = parsed.hostname.encode('idna').decode().lower().rstrip('.')
    if parsed.port not in (None, 80 if parsed.scheme == 'http' else 443):
        raise ValueError('Only standard web ports are supported.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('Local or internal addresses cannot be scanned.')
    if ':' in host:
        raise ValueError('Use a public company domain.')
    try:
        if not ipaddress.ip_address(host).is_global or ipaddress.ip_address(host).is_multicast:
            raise ValueError('Only public internet addresses can be scanned.')
    except ValueError as exc:
        if 'Only public' in str(exc):
            raise
        if ':' in host or host.replace('.', '').isdigit():
            raise ValueError('Use a public company domain.') from None
    return urlunsplit((parsed.scheme, host, parsed.path or '/', parsed.query, ''))


def public_ip(host):
    try:
        addresses = sorted({record[4][0] for record in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except OSError:
        raise ValueError('Website hostname could not be resolved.') from None
    if not addresses or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in addresses):
        raise ValueError('Website resolves to a private or reserved address.')
    return addresses[0]


def fetch_once(url):
    """Resolve once and connect to that vetted IP; retain TLS hostname checks."""
    parsed = urlsplit(normalize_url(url))
    ip = public_ip(parsed.hostname)
    options = {'timeout': urllib3.Timeout(connect=4, read=6), 'retries': False}
    if parsed.scheme == 'https':
        pool = urllib3.HTTPSConnectionPool(ip, port=443, server_hostname=parsed.hostname,
                assert_hostname=parsed.hostname, cert_reqs='CERT_REQUIRED', ca_certs=certifi.where(), **options)
    else:
        pool = urllib3.HTTPConnectionPool(ip, port=80, **options)
    response = None
    try:
        response = pool.urlopen('GET', urlunsplit(('', '', parsed.path or '/', parsed.query, '')),
                               headers={'Host': parsed.hostname, 'User-Agent': AGENT,
                                        'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'},
                               redirect=False, preload_content=False, retries=False)
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError('Page is larger than the 1 MB scan limit.')
        return response.status, dict(response.headers), body.decode('utf-8', errors='replace')
    except (urllib3.exceptions.HTTPError, OSError):
        raise ValueError('Website could not be reached securely within the time limit.') from None
    finally:
        if response is not None:
            response.close()
        pool.close()


class PublicCrawler:
    def __init__(self):
        self.robots = {}
        self.last_request = {}
        self.requests = 0
        self.deadline = time.monotonic() + 90

    def fetch(self, url):
        if time.monotonic() > self.deadline or self.requests >= 25:
            raise ValueError('Scan limit reached. Try fewer websites at once.')
        host = urlsplit(url).netloc
        delay = max(1, self.robots.get(host, (None, 1))[1])
        if delay > 10:
            raise ValueError('This site requests a crawl delay longer than this scanner supports.')
        wait = delay - (time.monotonic() - self.last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self.requests += 1
        self.last_request[host] = time.monotonic()
        return fetch_once(url)

    def allowed(self, url):
        p = urlsplit(url)
        if p.netloc not in self.robots:
            status, _, text = self.fetch(urlunsplit((p.scheme, p.netloc, '/robots.txt', '', '')))
            rules = RobotFileParser()
            if status == 404:
                rules.parse(['User-agent: *', 'Allow: /'])
            elif status == 200:
                rules.parse(text.splitlines())
            else:
                raise ValueError(f'Robots rules unavailable or restricted (HTTP {status}); skipped.')
            delay = rules.crawl_delay(AGENT) or rules.crawl_delay('*') or 1
            rate = rules.request_rate(AGENT) or rules.request_rate('*')
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
            self.robots[p.netloc] = (rules, delay)
        if not self.robots[p.netloc][0].can_fetch(AGENT, url):
            raise ValueError('This page is disallowed by the website’s robots rules.')

    def page(self, value):
        url = normalize_url(value)
        for _ in range(4):
            self.allowed(url)
            status, headers, text = self.fetch(url)
            headers = {k.lower(): v for k, v in headers.items()}
            if status in (301,302,303,307,308) and headers.get('location'):
                url = normalize_url(urljoin(url, headers['location']))
                continue
            if status != 200:
                raise ValueError(f'Website returned HTTP {status}; skipped.')
            if not any(t in headers.get('content-type','').lower() for t in ('text/html','application/xhtml+xml','text/plain')):
                raise ValueError('Only HTML and text pages are supported.')
            return url, text
        raise ValueError('Too many redirects; skipped.')


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text = []
        self.title = []
        self.site_name = ''
        self.in_title = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script','style','noscript'):
            self.hidden += 1
        if tag == 'title': self.in_title = True
        if tag == 'a' and attrs.get('href'): self.links.append(attrs['href'])
        if tag == 'meta' and attrs.get('property') == 'og:site_name': self.site_name = attrs.get('content','')

    def handle_endtag(self, tag):
        if tag in ('script','style','noscript'): self.hidden = max(0,self.hidden-1)
        if tag == 'title': self.in_title = False

    def handle_data(self, value):
        if self.in_title: self.title.append(value)
        if not self.hidden: self.text.append(value)


def domain(url):
    return urlsplit(url).hostname.removeprefix('www.')


def inspect_company(crawler, url):
    final, text = crawler.page(url)
    parser = PageParser(); parser.feed(text)
    company = ' '.join((parser.site_name or ''.join(parser.title) or domain(final)).split())[:255]
    company = re.split(r'\s+[|–—]\s+', company)[0]
    pages = [(final, parser)]
    warnings = []
    candidates = []
    for href in parser.links:
        if any(word in href.lower() for word in ('contact','about','team')):
            try:
                candidate = normalize_url(urljoin(final,href))
                if domain(candidate) == domain(final) and candidate not in candidates and candidate != final:
                    candidates.append(candidate)
            except ValueError:
                continue
    for candidate in candidates[:2]:
        try:
            address, body = crawler.page(candidate)
            if domain(address) != domain(final):
                warnings.append('A contact/about link redirected offsite; its content was excluded.')
                continue
            parsed = PageParser(); parsed.feed(body); pages.append((address, parsed))
        except ValueError as exc:
            warnings.append(str(exc))
    emails = {}
    for address, parsed in pages:
        published = ' '.join(parsed.text) + ' ' + ' '.join(unquote(h[7:].split('?')[0]) for h in parsed.links if h.lower().startswith('mailto:'))
        for email in re.findall(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}', published, flags=re.I):
            email = email.lower().rstrip('.')
            email_domain = email.split('@')[-1]
            if (email_domain == domain(final) or email_domain.endswith('.'+domain(final))) and len(email) <= 255:
                emails.setdefault(email, address)
    return {'company': company, 'domain': domain(final), 'url': final,
            'emails': [{'email': email, 'source': source} for email,source in sorted(emails.items())[:10]],
            'pages': [p[0] for p in pages], 'warnings': warnings, 'status': 'found'}


def inspect_directory(crawler, url):
    final, text = crawler.page(url)
    parser = PageParser(); parser.feed(text)
    candidates = {}
    excluded = {'linkedin.com','facebook.com','instagram.com','twitter.com','x.com','youtube.com','google.com'}
    for href in parser.links:
        if not href.startswith(('http://','https://')): continue
        try:
            candidate = normalize_url(href)
            host = domain(candidate)
            if host != domain(final) and not any(host == x or host.endswith('.'+x) for x in excluded):
                candidates.setdefault(host, urlunsplit((urlsplit(candidate).scheme,urlsplit(candidate).netloc,'/','','')))
        except ValueError:
            continue
    return {'directory': final, 'candidates': list(candidates.values())[:30],
            'note': 'These are external links, not verified leads. Select up to five company websites to scan.'}
