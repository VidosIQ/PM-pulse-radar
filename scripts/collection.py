"""Local collection -> validated snapshot -> staged HTML/XLSX -> publish locally."""
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'docs'
SOURCES = ('Product Radar', 'Habr / Product Radar', 'Show HN')

def validate(rows, source):
    if not rows or len(rows) > (5 if source == SOURCES[1] else 10):
        raise ValueError('Unexpected source record count')
    ids = set()
    hosts = {SOURCES[0]: 'productradar.ru', SOURCES[1]: 'habr.com', SOURCES[2]: 'news.ycombinator.com'}
    for r in rows:
        if r['source'] != source or not r['title'].strip() or not r.get('source_id'):
            raise ValueError('Missing title/ID or incorrect source')
        if r['source_id'] in ids:
            raise ValueError('Duplicate source ID')
        ids.add(r['source_id'])
        if urlparse(r['source_url']).hostname != hosts[source] or not r['source_url'].startswith('https://'):
            raise ValueError('Invalid source URL')
        for key in ('metric_value','comments_count'):
            v = r.get(key)
            if v is not None and (type(v) is not int or v < 0):
                raise ValueError('Invalid numeric indicator')
        if source != SOURCES[1] and r.get('metric_value') is None:
            raise ValueError('Missing metric')
        for key in ('fetched_at','published_at'):
            if r.get(key):
                if datetime.fromisoformat(r[key]).tzinfo is None:
                    raise ValueError('Date without timezone')
        if not r.get('fetched_at') or not r.get('response_sha256'):
            raise ValueError('Missing provenance')
        if source == SOURCES[0]:
            start, end = r['period'].split('/')
            if datetime.fromisoformat(start) > datetime.fromisoformat(end):
                raise ValueError('Invalid period')
        if r.get('product_url') and urlparse(r['product_url']).scheme not in ('https','http'):
            raise ValueError('Invalid product URL')

def collect(previous, module):
    rows, statuses = [], []
    for source, fn in zip(SOURCES, (module.radar, module.habr, module.hn)):
        module.ROWS.clear(); module.STATUS.clear()
        try:
            fn()
            fresh = list(module.ROWS)
            validate(fresh, source)
            status = dict(module.STATUS[-1])
            status['data_fetched_at'] = max(r['fetched_at'] for r in fresh)
        except Exception as error:
            fresh = [r for r in previous['records'] if r['source'] == source]
            if fresh:
                validate(fresh, source)
            status = {'source':source, 'result':'cached' if fresh else 'unavailable',
                      'records':len(fresh), 'error':str(error),
                      'data_fetched_at':max((r['fetched_at'] for r in fresh), default=None)}
        status['attempted_at'] = datetime.now(timezone.utc).isoformat()
        rows.extend(fresh); statuses.append(status)
        print(f"{source}: {status['result']}, {len(fresh)} records", flush=True)
    if not rows:
        raise ValueError('No usable data; current dashboard preserved')
    return rows, statuses

