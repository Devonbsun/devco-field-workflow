"""Local HTTP interface for Records & Pay; no external messages are sent here."""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import tracking as t
import tracking_export as packets
import daily_export as daily


def respond(handler, value, status=200):
    handler.reply(json.dumps(value), 'application/json', status)


def get(handler, app, path):
    if path not in ('/daily-export', '/daily-export-data', '/daily-export-file', '/tracking', '/tracking-data', '/tracking-history', '/tracking-file', '/tracking-photo', '/tracking-ledger'):
        return False
    root = app['ROOT']
    q = parse_qs(urlparse(handler.path).query)
    param = lambda key, default='': q.get(key, [default])[0]
    available = t.jobs(root)
    job = param('job') or app.get('active_job') or (available[0] if available else '')
    try:
        if path == '/daily-export':
            handler.reply((root / 'SYSTEM/daily_export.html').read_text())
        elif path == '/daily-export-data':
            respond(handler, daily.state(root, job))
        elif path == '/daily-export-file':
            file = daily.packet_file(root, job, param('id'), param('name'))
            download(handler, file.read_bytes(), 'application/zip', file.name)
        elif path == '/tracking':
            handler.reply((root / 'SYSTEM/tracking_ui.html').read_text())
        elif path == '/tracking-data':
            respond(handler, t.state(root, job))
        elif path == '/tracking-history':
            respond(handler, t.history(root, job, param('ju')))
        elif path == '/tracking-ledger':
            if job not in available: raise ValueError('Job not found.')
            download(handler, t.ledger_csv(root, job).encode(), 'text/csv; charset=utf-8', job + '_PAYMENT_TRACKER.csv')
        elif path == '/tracking-file':
            file = packets.packet_file(root, param('id'), param('name'))
            download(handler, file.read_bytes(), 'application/zip', file.name)
        elif path == '/tracking-photo':
            row = next((r for r in t.records(root, job) if r['ju'] == param('ju')), None)
            index = int(param('index', '-1'))
            if not row or index < 0 or index >= len(row['_photos']):
                raise ValueError('Photo not found.')
            file = row['_photos'][index]
            types = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.heic': 'image/heic'}
            handler.reply(file.read_bytes(), types[file.suffix.lower()])
    except (ValueError, FileNotFoundError) as error:
        respond(handler, {'error': str(error)}, 404)
    except Exception as error:
        print('TRACKING READ ERROR:', error, flush=True)
        respond(handler, {'error': 'Could not read tracking records. Refresh and try again.'}, 500)
    return True


def download(handler, body, mime, name):
    handler.send_response(200)
    handler.send_header('Content-Type', mime)
    handler.send_header('Content-Disposition', 'attachment; filename="' + name + '"')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.end_headers(); handler.wfile.write(body)


def post(handler, app):
    path = urlparse(handler.path).path
    if path not in ('/daily-export-build', '/daily-export-share', '/tracking-action', '/tracking-export', '/tracking-sent', '/tracking-share'):
        return False
    try:
        size = int(handler.headers.get('Content-Length', '0'))
        if not 0 < size <= 200000 or handler.headers.get_content_type() != 'application/json':
            raise ValueError('Invalid tracking request.')
        origin = handler.headers.get('Origin')
        if origin and origin != 'http://127.0.0.1:' + str(handler.server.server_port):
            raise ValueError('Invalid request origin.')
        data = json.loads(handler.rfile.read(size))
        if not isinstance(data, dict): raise ValueError('Invalid request.')
        root = app['ROOT']
        if path == '/daily-export-build': result = daily.create(root, data.get('job'))
        elif path == '/daily-export-share':
            import subprocess
            file = daily.packet_file(root, data.get('job'), data.get('id'), data.get('name'))
            command = Path('/data/data/com.termux/files/usr/bin/termux-open')
            if not command.exists(): raise ValueError('Use Download or open the saved folder on your phone.')
            subprocess.run([str(command), '--send', '--chooser', '--content-type', 'application/zip', str(file)], check=True, capture_output=True, timeout=10)
            result = {'ok': True, 'message': 'Choose where to send this day’s packet in the phone share menu.'}
        elif path == '/tracking-action': result = t.mutate(root, data)
        elif path == '/tracking-export': result = packets.create(root, data.get('job'), data.get('selection'), data.get('audience'))
        elif path == '/tracking-sent': result = packets.mark_sent(root, data.get('id'), data.get('request_id'), str(data.get('reference', '')))
        else: result = packets.share(root, data.get('id'), data.get('name'))
        respond(handler, result)
    except t.Conflict as error:
        respond(handler, {'error': str(error)}, 409)
    except (ValueError, TypeError, KeyError) as error:
        respond(handler, {'error': str(error)}, 400)
    except Exception as error:
        print('TRACKING WRITE ERROR:', error, flush=True)
        respond(handler, {'error': 'The action could not finish. Refresh to check its status before retrying.'}, 500)
    return True
