import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import os, json, hashlib
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

KEYWORDS = [
    "runway", "kling", "ai video", "generative", "motion",
    "sora", "pika", "filmmaking", "video production", "cinematograph"
]

RSS_FEEDS = {
    "ai": [
        "https://www.indeed.com/rss?q=AI+video+production&l=London&radius=25&sort=date",
        "https://www.indeed.com/rss?q=AI+video+editor&l=Remote&sort=date",
        "https://www.indeed.com/rss?q=generative+video&l=Remote&sort=date",
    ],
    "film": [
        "https://www.indeed.com/rss?q=film+production&l=London&radius=25&sort=date",
        "https://www.indeed.com/rss?q=video+producer&l=London&radius=25&sort=date",
    ]
}

SCRAPE_TARGETS = [
    {
        "name": "Mandy.com",
        "url": "https://www.mandy.com/uk/job/list?keywords=video+production",
        "job_selector": ".job-listing",
        "title_selector": ".job-title",
        "link_selector": "a",
        "base_url": "https://www.mandy.com"
    },
    {
        "name": "ProductionBase",
        "url": "https://www.productionbase.co.uk/jobs?keywords=video",
        "job_selector": ".job-item",
        "title_selector": ".job-title",
        "link_selector": "a",
        "base_url": "https://www.productionbase.co.uk"
    }
]

SEEN_JOBS_FILE = "seen_jobs.json"
MAX_PER_FEED = 5


def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, 'r') as f:
            return set(json.load(f))
    return set()


def save_seen_jobs(seen):
    with open(SEEN_JOBS_FILE, 'w') as f:
        json.dump(list(seen), f)


def make_job_id(title, link):
    return hashlib.md5(f'{title}{link}'.encode()).hexdigest()


def matches_keywords(job):
    text = (job.get('title', '') + ' ' + job.get('summary', '')).lower()
    return any(kw in text for kw in KEYWORDS)


def fetch_rss_jobs(url, limit=5):
    try:
        feed = feedparser.parse(url)
        jobs = []
        for entry in feed.entries[:limit]:
            jobs.append({
                'title': entry.get('title', 'No title'),
                'company': entry.get('source', {}).get('title', 'Unknown'),
                'link': entry.get('link', '#'),
                'published': entry.get('published', ''),
                'summary': entry.get('summary', '')[:200],
                'source': 'Indeed'
            })
        return jobs
    except Exception as e:
        print(f'RSS error {url}: {e}')
        return []


def scrape_jobs(target):
    jobs = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(target['url'], headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        listings = soup.select(target['job_selector'])[:MAX_PER_FEED]
        for item in listings:
            title_el = item.select_one(target['title_selector'])
            link_el = item.select_one(target['link_selector'])
            if not title_el:
                continue
            href = link_el['href'] if link_el and link_el.get('href') else '#'
            if href.startswith('/'):
                href = target['base_url'] + href
            jobs.append({
                'title': title_el.get_text(strip=True),
                'company': '', 'link': href,
                'published': '', 'summary': '',
                'source': target['name']
            })
    except Exception as e:
        print(f'Scrape error {target["name"]}: {e}')
    return jobs


def filter_new(jobs, seen):
    new_jobs = []
    for job in jobs:
        jid = make_job_id(job['title'], job['link'])
        if jid not in seen:
            job['id'] = jid
            new_jobs.append(job)
    return new_jobs


def build_html(ai_jobs, film_jobs, scraped_jobs):
    today = datetime.now(timezone.utc).strftime('%B %d, %Y')
    total = len(ai_jobs) + len(film_jobs) + len(scraped_jobs)

    def job_row(j):
        badge_color = {'Indeed': '#e8f0fe', 'Mandy.com': '#fce8e6',
                       'ProductionBase': '#e6f4ea'}.get(j.get('source', ''), '#f5f5f5')
        return f'''
        <tr><td style="padding:10px;border-bottom:1px solid #eee;">
          <a href="{j['link']}" style="font-weight:bold;color:#1a0dab;">{j['title']}</a><br>
          <small style="color:#666;">{j.get('company', '')} {('· ' + j['published']) if j.get('published') else ''}</small>
          <span style="background:{badge_color};border-radius:3px;padding:1px 6px;font-size:11px;margin-left:6px;">{j.get('source', '')}</span><br>
          {f'<small>{j["summary"]}</small>' if j.get('summary') else ''}
        </td></tr>'''

    def section(title, emoji, jobs, more_links):
        if not jobs:
            return f'<h3>{emoji} {title}</h3><p style="color:#999;">No new listings today.</p>'
        rows = ''.join(job_row(j) for j in jobs[:5])
        links = ' | '.join(f'<a href="{u}">→ {l}</a>' for l, u in more_links)
        return f'<h3>{emoji} {title}</h3><table width="100%">{rows}</table><p>{links}</p>'

    ai_s = section('AI Video Jobs (New Today)', '🤖', ai_jobs, [
        ('Curious Refuge', 'https://curiousrefuge.com/ai-jobs-board'),
        ('Indeed AI Video', 'https://www.indeed.com/q-ai-video-l-remote-jobs.html'),
    ])
    film_s = section('Film & Video Production (New Today)', '🎥', film_jobs, [
        ('Indeed London Film', 'https://uk.indeed.com/q-remote-working-film-production-l-london-jobs.html'),
        ('Glassdoor London', 'https://www.glassdoor.co.uk'),
    ])
    scraped_s = section('UK Production Boards (New Today)', '🎬', scraped_jobs, [
        ('Mandy.com', 'https://www.mandy.com/uk/job/list'),
        ('ProductionBase', 'https://www.productionbase.co.uk/jobs'),
    ])
    return f'''<html><body style="font-family:sans-serif;max-width:620px;margin:auto;">
      <div style="background:#111;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;">Daily Job Digest</h2>
        <p style="color:#aaa;margin:4px 0 0;">{today} · {total} new listings</p>
      </div>
      <div style="padding:20px;border:1px solid #eee;border-radius:0 0 8px 8px;">
        {ai_s}{film_s}{scraped_s}
        <hr><p style="font-size:11px;color:#999;">Sent daily at 1pm GMT via GitHub Actions</p>
      </div></body></html>'''


def build_text(ai_jobs, film_jobs, scraped_jobs):
    today = datetime.now(timezone.utc).strftime('%B %d, %Y')
    total = len(ai_jobs) + len(film_jobs) + len(scraped_jobs)

    def section(title, jobs):
        if not jobs:
            return f'{title}\nNo new listings today.\n'
        rows = []
        for job in jobs[:5]:
            company = f" - {job.get('company', '')}" if job.get('company') else ''
            source = f" [{job.get('source', '')}]" if job.get('source') else ''
            rows.append(f"- {job['title']}{company}{source}\n  {job['link']}")
        return f'{title}\n' + '\n'.join(rows) + '\n'

    parts = [
        f'Daily Job Digest',
        f'{today} | {total} new listings',
        '',
        section('AI Video Jobs', ai_jobs),
        section('Film & Video Production', film_jobs),
        section('UK Production Boards', scraped_jobs),
        'Sent daily via GitHub Actions.',
    ]
    return '\n'.join(parts)


def send_email(html, text, total):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    debug_suffix = f" [{timestamp}]" if os.environ.get("DEBUG_EMAIL_SUBJECT") == "1" else ""
    subject = f'Daily Job Digest: {total} new job{"s" if total != 1 else ""} ({datetime.now(timezone.utc).strftime("%b %d")}){debug_suffix}'
    if total == 0:
        subject = f'Daily Job Digest: no new listings ({datetime.now(timezone.utc).strftime("%b %d")}){debug_suffix}'
    recipients = [email.strip() for email in os.environ['RECIPIENT_EMAIL'].split(',') if email.strip()]
    print(f"Sending to: {', '.join(recipients)}")
    print(f"Subject: {subject}")
    message = Mail(
        from_email='ea2sakaar@agentmail.to',
        to_emails=recipients,
        subject=subject,
        plain_text_content=text,
        html_content=html
    )
    sg = SendGridAPIClient(os.environ['SENDGRID_API_KEY'])
    sg.send(message)
    print(f'Email sent. {total} new jobs.')


def commit_seen_jobs():
    os.system('git config user.email "actions@github.com"')
    os.system('git config user.name "GitHub Actions"')
    os.system(f'git add {SEEN_JOBS_FILE}')
    os.system('git commit -m "Update seen jobs [skip ci]" || echo "Nothing to commit"')
    os.system('git push')


if __name__ == '__main__':
    seen = load_seen_jobs()
    raw_ai, raw_film = [], []
    for url in RSS_FEEDS['ai']:
        raw_ai += fetch_rss_jobs(url)
    for url in RSS_FEEDS['film']:
        raw_film += fetch_rss_jobs(url)
    raw_scraped = []
    for target in SCRAPE_TARGETS:
        raw_scraped += scrape_jobs(target)

    ai_jobs = filter_new([j for j in raw_ai if matches_keywords(j)], seen)
    film_jobs = filter_new([j for j in raw_film if matches_keywords(j)], seen)
    scraped_jobs = filter_new(raw_scraped, seen)

    for job in ai_jobs + film_jobs + scraped_jobs:
        seen.add(job['id'])
    save_seen_jobs(seen)

    total = len(ai_jobs) + len(film_jobs) + len(scraped_jobs)
    html = build_html(ai_jobs, film_jobs, scraped_jobs)
    text = build_text(ai_jobs, film_jobs, scraped_jobs)
    send_email(html, text, total)
    commit_seen_jobs()
