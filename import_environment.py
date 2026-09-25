"""Download a bounded, provenance-preserving Natural England SSSI polygon sample.

Standard library only. Coordinates are actual source polygon vertices reprojected
by ArcGIS to WGS84 longitude/latitude; no bounding-box geometry is fabricated.
"""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bbox', nargs=4, type=float, metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'))
    parser.add_argument('--output', type=Path, default=Path('.local/environment'))
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name('environment_sources.json').read_text())
    bbox = args.bbox or config['default_bbox_wgs84']
    west, south, east, north = bbox
    if not (all(math.isfinite(v) for v in bbox) and -180 <= west < east <= 180
            and -90 <= south < north <= 90 and east-west <= .25 and north-south <= .25):
        parser.error('bbox must be ordered WGS84 coordinates, at most 0.25 degrees on either axis')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    records = []

    def fetch(url, filename, params=None):
        nonlocal downloaded
        if params:
            url += '?' + urlencode(params)
        remaining = config['maximum_total_download_bytes'] - downloaded
        if remaining <= 0:
            raise RuntimeError('10 MiB aggregate download cap reached')
        with urlopen(Request(url, headers={'User-Agent': 'soil-public-environment-import/1.0'}), timeout=45) as response:
            raw = response.read(remaining + 1)
        if len(raw) > remaining:
            raise RuntimeError('Response exceeds aggregate 10 MiB download cap; narrow the bbox')
        downloaded += len(raw)
        data = json.loads(raw)
        if 'error' in data:
            raise RuntimeError(f'ArcGIS error: {data["error"]}')
        (output / filename).write_bytes(raw)
        records.append({'url': url, 'file': filename, 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(),
                        'retrieved_at_utc': datetime.now(timezone.utc).isoformat()})
        return data

    service = fetch(config['service_url'], 'service.json', {'f': 'json'})
    if service.get('serviceItemId') != config['item_id']:
        raise RuntimeError('Service item changed; source ownership/licence requires review')
    item = fetch('https://www.arcgis.com/sharing/rest/content/items/' + config['item_id'],
                 'item.json', {'f': 'json'})
    licence_text = item.get('licenseInfo', '')
    if not ('open government licence' in licence_text.lower()
            or 'open-government-licence' in licence_text.lower()):
        raise RuntimeError('Source item does not confirm Open Government Licence; inspect item.json')
    layer_url = config['service_url'] + '/' + str(config['layer_id'])
    layer = fetch(layer_url, 'layer.json', {'f': 'json'})
    if layer.get('geometryType') != 'esriGeometryPolygon':
        raise RuntimeError('Expected polygon source layer')
    params = {'where': '1=1', 'geometry': ','.join(map(str, bbox)),
              'geometryType': 'esriGeometryEnvelope', 'inSR': 4326,
              'spatialRel': 'esriSpatialRelIntersects'}
    count = fetch(layer_url + '/query', 'count.json',
                  dict(params, f='json', returnCountOnly='true'))['count']
    features = fetch(layer_url + '/query', 'sssi.geojson',
                     dict(params, f='geojson', outFields='*', outSR=4326,
                          returnGeometry='true', resultRecordCount=config['maximum_features'],
                          orderByFields=layer['objectIdField']))
    if features.get('type') != 'FeatureCollection':
        raise RuntimeError('Expected GeoJSON FeatureCollection')
    rows = features['features']
    if len(rows) > config['maximum_features']:
        raise RuntimeError('Server ignored feature limit')
    for row in rows:
        geometry = row.get('geometry') or {}
        if geometry.get('type') not in ('Polygon', 'MultiPolygon') or not geometry.get('coordinates'):
            raise RuntimeError('Null or nonpolygon geometry returned')
    exceeded = bool(features.get('exceededTransferLimit') or
                    features.get('properties', {}).get('exceededTransferLimit'))
    complete = not exceeded and len(rows) == count
    provenance = {
        'schema_version': 1, 'dataset': config['dataset'], 'publisher': config['publisher'],
        'source': config, 'source_item_owner': item.get('owner'),
        'licence_as_recorded': licence_text,
        'copyright_as_recorded': layer.get('copyrightText') or service.get('copyrightText'),
        'bbox_wgs84': bbox, 'selection': 'full source geometries intersecting bbox; not clipped',
        'input_crs_as_recorded': layer.get('extent', {}).get('spatialReference'),
        'output_crs': 'EPSG:4326', 'coordinate_order': ['longitude', 'latitude'],
        'coordinate_units': 'degrees', 'attribute_units': 'as recorded in source field metadata; not inferred',
        'fields_as_recorded': layer.get('fields', []),
        'source_editing_info_as_recorded': layer.get('editingInfo'),
        'query_count': count, 'feature_count': len(rows),
        'exceeded_transfer_limit': exceeded, 'complete_for_bbox_query': complete,
        'completeness_note': 'Count and feature requests are separate snapshots; no dataset-wide completeness claim.',
        'geometry': 'Actual source Polygon/MultiPolygon vertices; server reprojection to WGS84; no simplification requested.',
        'files': records, 'downloaded_bytes': downloaded,
        'limitations': config['scope']}
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'features': len(rows), 'query_count': count,
                      'complete_for_bbox_query': complete, 'downloaded_bytes': downloaded}))
    if not complete:
        raise SystemExit('Partial result retained with provenance; narrow bbox before using for screening')


if __name__ == '__main__':
    main()
