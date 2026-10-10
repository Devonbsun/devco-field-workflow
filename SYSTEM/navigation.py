"""Resolve every navigation request against the requested JU's saved coordinates."""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from job_records import _parse_info
from record_editor import folder_for, RECORD_LOCK


def coordinate(value, limit):
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError('This JU has no valid coordinates. Check its saved location.')
    if not number.is_finite() or abs(number) > limit:
        raise ValueError('This JU has invalid coordinates. Check its saved location.')
    return format(number, 'f')


def target(app, job, ju):
    with RECORD_LOCK:
        folder = folder_for(app, job, ju)
        info = _parse_info(folder / 'transfer_info.txt')
        lat = coordinate(info.get('Latitude', ''), 90)
        lon = coordinate(info.get('Longitude', ''), 180)
        if Decimal(lat) == 0 and Decimal(lon) == 0:
            raise ValueError('This JU has a placeholder location (0, 0). Check its saved location.')
        return {'job': job, 'ju': ju, 'lat': lat, 'lon': lon}


def maps_url(point):
    return 'https://www.google.com/maps/dir/?' + urlencode({
        'api': '1', 'destination': point['lat'] + ',' + point['lon'],
        'travelmode': 'driving', 'dir_action': 'navigate',
    })


def ju_url(path, job, ju):
    return path + '?' + urlencode({'job': job, 'ju': ju})
