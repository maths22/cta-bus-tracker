import os
from xml.etree import ElementTree
import urllib.request
import gzip
import time
from datetime import datetime, timezone, timedelta
from backports.zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
import boto3
from chalice import Chalice, NotFoundError

app = Chalice(app_name='cta-bus-tracker')
_TABLE = None

ssm_client = boto3.client('ssm')
environment = os.environ['ENVIRONMENT']
raw_config = ssm_client.get_parameters_by_path(Path=f'/cta-bus-tracker/{environment}', Recursive=True, WithDecryption=True)
config = { entry['Name'].replace(f'/cta-bus-tracker/{environment}/', '', 1) : entry['Value'] for entry in raw_config['Parameters'] }

@app.route('/available/{year}/{month}/{day}', cors=True)
def available(year, month, day):
    reqZone = None
    if app.current_request.query_params != None:
        reqZone = app.current_request.query_params.get('timezone')
    if reqZone == None:
        reqZone = "UTC"
    start = datetime(int(year), int(month), int(day), tzinfo=ZoneInfo(reqZone)).astimezone(timezone.utc)
    end = start + timedelta(1)

    response_start = get_app_table().get_item(
        Key={
            'key': 'archive_index',
            'range_key': start.isoformat().split('T')[0].replace('-','/')
        }
    )
    response_end = get_app_table().get_item(
        Key={
            'key': 'archive_index',
            'range_key': end.isoformat().split('T')[0].replace('-','/')
        }
    )

    start_entries = response_start.get('Item', { 'entries': dict() })['entries']
    end_entries = response_end.get('Item', { 'entries': dict() })['entries']
    entries = {**start_entries, **end_entries}
    filtered_entries = dict(filter(lambda elem: datetime.fromtimestamp(int(elem[0]), tz=timezone.utc) >= start and datetime.fromtimestamp(int(elem[0]), tz=timezone.utc) <= end,
        entries.items()))

    if len(filtered_entries) == 0:
        raise NotFoundError(f'No archives available for {year}-{month}-{day}')
    return filtered_entries

@app.route('/runs/{vid}', cors=True)
def available(vid):
    start = None
    if app.current_request.query_params != None:
        start = app.current_request.query_params.get('start')
    if start == None:
        start = datetime.now()
    else:
        start = datetime.utcfromtimestamp(int(start))
    
    ret = []

    with psycopg.connect(db_connection_string(), row_factory=dict_row) as conn:
        cur = conn.execute("SELECT rt, tablockid, max(tmstmp) at time zone 'america/chicago' at time zone 'utc' as end, min(tmstmp) at time zone 'america/chicago' at time zone 'utc' as start FROM vehicles WHERE vid = %(vid)s and tmstmp <= %(start)s and tmstmp >= %(start)s - INTERVAL '90 days' GROUP BY rt, tablockid, date_trunc('day', tmstmp) ORDER BY max(tmstmp) desc",
            {'vid': vid, 'start': start})
        for record in cur:
            ret.append({
                'rt': record['rt'],
                'tablockid': record['tablockid'],
                'garage': tablockidToGarage(record['tablockid']),
                'start': datetime.timestamp(record['start']),
                'end': datetime.timestamp(record['end']),
            })

    return {
        'runs': ret,
        'next': int(datetime.timestamp(start - timedelta(days=90)))
    }

@app.schedule('cron(*/10 * * * ? *)')
def refresh(evt):
    to_upload = gzip.compress(b"<?xml version=\"1.0\"?>\n<?xml-stylesheet type=\"text/xsl\" href=\"/bus-rte.xsl\"?>" + ctaData())
    ts = int(time.time())
    time_path = datetime.fromtimestamp(ts).strftime('%Y/%m/%d')
    dest_path = f'archive/{time_path}/buses-in-service-{ts}.xml'
    now = datetime.now()
    now_plus_10 = now + timedelta(minutes = 10)
    client = boto3.client('s3')
    client.put_object(Body=to_upload, Bucket=config['s3.bucket_name'], Key=dest_path, ContentEncoding='gzip', ContentType='text/xml')
    client.put_object(Body=to_upload, Bucket=config['s3.bucket_name'], Key='buses-in-service.xml', ContentEncoding='gzip', ContentType='text/xml', Expires=now_plus_10)

    response = get_app_table().get_item(
        Key={
            'key': 'archive_index',
            'range_key': time_path
        }
    )

    entries = dict()
    if 'Item' in response.keys():
        entries = response['Item']['entries']
    entries[str(ts)] = dest_path
    get_app_table().put_item(
        Item={
            'key': 'archive_index',
            'range_key': time_path,
            'entries': entries
        }
    )

@app.on_s3_event(bucket=config['s3.bucket_name'], events=['s3:ObjectCreated:*'], prefix="archive/")
def process_new_archive(event):
    import_archive_to_postgres(event.bucket, event.key)

def import_archive_to_postgres(bucket, key):
    client = boto3.client('s3')
    obj = client.get_object(Bucket=bucket, Key=key)
    root = ElementTree.fromstring(gzip.decompress(obj['Body'].read()))
    with psycopg.connect(db_connection_string(), row_factory=dict_row) as conn:
        for route in root.findall('./route'):
            conn.execute('INSERT INTO routes (rt, rtnm, rtclr, rtdd) VALUES (%s, %s, %s, %s) ON CONFLICT (rt) DO UPDATE SET rtnm = EXCLUDED.rtnm, rtclr = EXCLUDED.rtclr, rtdd = EXCLUDED.rtdd',
                [
                    route.find('./rt').text,
                    route.find('./rtnm').text if route.find('./rtnm') != None else None,
                    route.find('./rtclr').text if route.find('./rtclr') != None else None,
                    route.find('./rtdd').text if route.find('./rtdd') != None else None,
                ])
        for vehicle in root.findall('./vehicle'):
            conn.execute('INSERT INTO vehicles (vid, tmstmp, lat_long, hdg, pid, rt, des, pdist, tablockid, tatripid) VALUES (%s, %s, POINT(%s, %s)::geometry, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (vid, tmstmp) DO NOTHING',
                [
                    vehicle.find('./vid').text,
                    vehicle.find('./tmstmp').text if vehicle.find('./tmstmp') != None else None,
                    vehicle.find('./lat').text if vehicle.find('./lat') != None else None,
                    vehicle.find('./long').text if vehicle.find('./long') != None else None,
                    vehicle.find('./hdg').text if vehicle.find('./hdg') != None else None,
                    vehicle.find('./pid').text if vehicle.find('./pid') != None else None,
                    vehicle.find('./rt').text if vehicle.find('./rt') != None else None,
                    vehicle.find('./des').text if vehicle.find('./des') != None else None,
                    vehicle.find('./pdist').text if vehicle.find('./pdist') != None else None,
                    vehicle.find('./tablockid').text if vehicle.find('./tablockid') != None else None,
                    vehicle.find('./tatripid').text if vehicle.find('./tatripid') != None else None,
                ])
        conn.commit()


def ctaData():
  api_key = config['cta.api_key']
  tree = ElementTree.ElementTree(file=urllib.request.urlopen(f'http://www.ctabustracker.com/bustime/api/v1/getroutes?key={api_key}'))
  for route in tree.getroot().findall('./*/rt'):
    route_num = route.text
    route_tree = ElementTree.ElementTree(file=urllib.request.urlopen(f'http://www.ctabustracker.com/bustime/api/v1/getvehicles?key={api_key}&rt={route_num}'))
    for child in route_tree.getroot():
      tree.getroot().append(child)
  time_tree = ElementTree.ElementTree(file=urllib.request.urlopen(f'http://www.ctabustracker.com/bustime/api/v1/gettime?key={api_key}'))
  for child in time_tree.getroot():
      tree.getroot().append(child)
  return ElementTree.tostring(tree.getroot())

def tablockidToGarage(tablockid):
    garageId = tablockid.split("-")[1][0]
    return {
        '1': '1 (103rd)',
        '2': 'K (Kedzie)',
        '4': 'F (Forest Glen)',
        '5': 'P (North Park)',
        '6': '6 (74th)',
        '7': '7 (77th)',
        '8': '5 (Chicago)',
    }.get(garageId, 'unknown')

def get_app_table():
    global _TABLE
    if _TABLE is None:
        _TABLE = boto3.resource('dynamodb').Table(config['archive_table_name'])
        
    return _TABLE

def db_connection_string():
    return f'host={config["db.host"]} user={config["db.username"]} password={config["db.password"]} dbname={config["db.database"]}'

def main():
    import_archive_to_postgres('cta-bus-history-tracker', 'buses-in-service.xml')

if __name__ == '__main__':
    main()
