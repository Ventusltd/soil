"""Bounded import of open ground records for one British National Grid box.

Only sources marked usable and import in ground_sources.json are fetched,
sequentially, with a byte cap. Raw responses are cached under
E:\\world-cache\\ground\\<site>\\ (or --cache). Geometry is clipped to the box
and written in EPSG:27700 metres. Layers that are not imported stay null
(missing); layers queried with no hits are [] (none found).
"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
BNG = 'http://www.opengis.net/def/crs/EPSG/0/27700'
UA = 'soil-ground-import/1.0 (bounded, sequential)'
MAX_BYTES = 40 * 1024 * 1024
MAX_PAGES = 20
PAUSE_S = 1.0


# ---------- geometry (pure, tested) ----------

def clip_ring(ring, box):
    """Sutherland-Hodgman clip of one ring to box (e0, n0, e1, n1).
    Returns an open ring (no repeated closing vertex); [] if nothing is left."""
    e0, n0, e1, n1 = box
    pts = [tuple(p[:2]) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    edges = [(0, e0, True), (0, e1, False), (1, n0, True), (1, n1, False)]
    for axis, lim, keep_greater in edges:
        if not pts:
            break
        inside = (lambda p: p[axis] >= lim) if keep_greater else (lambda p: p[axis] <= lim)
        out = []
        prev = pts[-1]
        for cur in pts:
            cin, pin = inside(cur), inside(prev)
            if cin != pin:
                t = (lim - prev[axis]) / (cur[axis] - prev[axis])
                x = prev[0] + t * (cur[0] - prev[0])
                y = prev[1] + t * (cur[1] - prev[1])
                out.append((lim, y) if axis == 0 else (x, lim))
            if cin:
                out.append(cur)
            prev = cur
        pts = out
    return pts if len(pts) >= 3 and abs(ring_area(pts)) > 1e-6 else []


def ring_area(pts):
    s = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        s += x0 * y1 - x1 * y0
    return s / 2


def clip_polygon(rings, box):
    """rings[0] is the exterior. Returns clipped rings, or None if the exterior misses the box."""
    outer = clip_ring(rings[0], box)
    if not outer:
        return None
    holes = [h for h in (clip_ring(r, box) for r in rings[1:]) if h]
    return [[[round(x, 2), round(y, 2)] for x, y in r] for r in [outer] + holes]


def polygons_of(geometry):
    if not geometry:
        return []
    if geometry['type'] == 'Polygon':
        return [geometry['coordinates']]
    if geometry['type'] == 'MultiPolygon':
        return geometry['coordinates']
    raise ValueError('Unexpected geometry type ' + geometry['type'])


def borehole_record(props):
    """Map a SOBI record. Missing or coded (negative) lengths stay missing."""
    rec = {'e': props['easting'], 'n': props['northing'], 'id': props['reference'],
           'name': props.get('name'), 'precision': props.get('precision')}
    length = props.get('length')
    if isinstance(length, (int, float)) and length >= 0:
        rec['drilled_length_m'] = float(length)
    else:
        rec['length_code_as_recorded'] = length
    for key in ('scan_url', 'ags_log_url'):
        if props.get(key):
            rec['log_url' if key == 'scan_url' else 'ags_log_url'] = props[key]
    return rec


# ---------- projection ----------

def ostn15(cache_proj):
    """WGS84 lon/lat -> EPSG:27700 using OSTN15 only; refuses Helmert fallbacks."""
    import pyproj
    from pyproj.transformer import TransformerGroup
    pyproj.datadir.append_data_dir(str(cache_proj))
    group = TransformerGroup('EPSG:4326', 'EPSG:27700', always_xy=True)
    chosen = [t for t in group.transformers if 'OSGB36 to WGS 84 (9)' in t.description]
    if not chosen:
        raise RuntimeError('OSTN15 grid not available; place uk_os_OSTN15_NTv2_OSGBtoETRS.tif '
                           'from https://cdn.proj.org/ in ' + str(cache_proj))
    fwd = chosen[0]
    inv = [t for t in TransformerGroup('EPSG:27700', 'EPSG:4326', always_xy=True).transformers
           if 'OSGB36 to WGS 84 (9)' in t.description][0]
    return fwd, inv


def project_rings(rings, fwd):
    out = []
    for r in rings:
        xs, ys = fwd.transform([p[0] for p in r], [p[1] for p in r])
        out.append(list(zip(xs, ys)))
    return out


# ---------- fetch ----------

class Fetcher:
    def __init__(self, cache):
        self.cache = cache
        self.total = 0
        self.log = []
        self.last = 0.0

    def get(self, url, params, name):
        full = url + ('?' + urlencode(params) if params else '')
        wait = PAUSE_S - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        remaining = MAX_BYTES - self.total
        if remaining <= 0:
            raise RuntimeError('aggregate download cap reached')
        with urlopen(Request(full, headers={'User-Agent': UA, 'Accept': 'application/geo+json, application/json'}),
                     timeout=90) as resp:
            raw = resp.read(remaining + 1)
            crs_header = resp.headers.get('Content-Crs')
        self.last = time.monotonic()
        if len(raw) > remaining:
            raise RuntimeError('response exceeds download cap: ' + full)
        self.total += len(raw)
        (self.cache / name).write_bytes(raw)
        entry = {'url': full, 'file': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                 'retrieved_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        if crs_header:
            entry['content_crs'] = crs_header
        self.log.append(entry)
        data = json.loads(raw)
        if isinstance(data, dict) and 'error' in data:
            raise RuntimeError(f'service error {data["error"]} for {full}')
        return data, entry


def ogc_pages(fetcher, url, params, stem):
    feats, files, matched = [], [], None
    next_url, next_params, page = url, params, 0
    while next_url:
        if page >= MAX_PAGES:
            raise RuntimeError('page cap reached for ' + url)
        data, entry = fetcher.get(next_url, next_params, f'{stem}-{page}.json')
        files.append(entry['sha256'])
        feats += data.get('features', [])
        matched = data.get('numberMatched', matched)
        nxt = [l['href'] for l in data.get('links', []) if l.get('rel') == 'next']
        next_url, next_params, page = (nxt[0] if nxt else None), None, page + 1
    return feats, matched, files


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--site', default='open-land-01')
    ap.add_argument('--e0', type=float, default=399104)
    ap.add_argument('--n0', type=float, default=208896)
    ap.add_argument('--size', type=float, default=2048)
    ap.add_argument('--margin', type=float, default=500)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--cache', type=Path)
    a = ap.parse_args()
    if not (0 < a.size <= 5000 and 0 <= a.margin <= 2000):
        ap.error('size must be in (0, 5000] m and margin in [0, 2000] m')
    box = (a.e0 - a.margin, a.n0 - a.margin, a.e0 + a.size + a.margin, a.n0 + a.size + a.margin)
    if not (0 <= box[0] and box[2] <= 700000 and 0 <= box[1] and box[3] <= 1300000):
        ap.error('box outside British National Grid')
    out = a.out or Path(r'E:\lidar-out') / a.site / 'ground.json'
    cache = a.cache or Path(r'E:\world-cache\ground') / a.site
    cache.mkdir(parents=True, exist_ok=True)
    fwd, inv = ostn15(Path(r'E:\world-cache\ground\proj'))
    manifest = json.loads((ROOT / 'ground_sources.json').read_text(encoding='utf-8'))
    src = {s['id']: s for s in manifest['sources']}
    lons, lats = inv.transform([box[0], box[2], box[0], box[2]], [box[1], box[1], box[3], box[3]])
    pad = 0.0005
    bbox84 = [min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad]
    f = Fetcher(cache)
    sources_out, notes = [], []

    def record(sid, **extra):
        s = src[sid]
        rec = {k: s[k] for k in ('id', 'title', 'publisher', 'licence', 'attribution', 'verified_url') if k in s}
        rec['licence_verified_on'] = manifest['verified_on']
        rec.update(extra)
        sources_out.append(rec)

    def geology(sid, collection):
        feats, matched, shas = ogc_pages(f, src[sid]['service'],
                                         {'f': 'json', 'bbox': ','.join(f'{v:.6f}' for v in bbox84), 'limit': 500}, collection)
        rows = []
        for feat in feats:
            p = feat['properties']
            for poly in polygons_of(feat['geometry']):
                clipped = clip_polygon(project_rings(poly, fwd), box)
                if clipped:
                    rows.append({'polygon': clipped, 'code': p.get('lex_rcs'), 'name': p.get('lex_d'),
                                 'lithology': p.get('rcs_d'), 'age': ' to '.join(x for x in (p.get('max_period'), p.get('min_period')) if x),
                                 'status': src[sid]['status'], 'scale': src[sid]['scale'], 'source': sid})
        record(sid, service=src[sid]['service'], query_bbox_crs84=bbox84, number_matched=matched,
               features_returned=len(feats), polygons_in_box=len(rows), raw_sha256=shas,
               complete=matched is None or matched == len(feats), limitations=src[sid]['limitations'])
        return rows

    ground = {'bedrock': geology('bgs-geology-625k-bedrock', 'bgsgeology625kbedrock'),
              'superficial': geology('bgs-geology-625k-superficial', 'bgsgeology625ksuperficial')}

    feats, matched, shas = ogc_pages(f, src['bgs-sobi']['service'],
                                     {'f': 'json', 'bbox': ','.join(f'{v:.6f}' for v in bbox84), 'limit': 1000}, 'sobi')
    bh, worst = [], 0.0
    for feat in feats:
        p = feat['properties']
        if not (box[0] <= p['easting'] <= box[2] and box[1] <= p['northing'] <= box[3]):
            continue
        rec = borehole_record(p)
        x, y = fwd.transform(*feat['geometry']['coordinates'][:2])
        worst = max(worst, abs(x - p['easting']), abs(y - p['northing']))
        bh.append(rec)
    bh.sort(key=lambda r: r['id'])
    ground['boreholes'] = bh
    record('bgs-sobi', service=src['bgs-sobi']['service'], number_matched=matched, in_box=len(bh), raw_sha256=shas,
           complete=matched is None or matched == len(feats),
           coordinates='easting/northing as recorded by BGS (EPSG:27700)',
           geometry_vs_recorded_max_abs_m=round(worst, 3), scans=src['bgs-sobi']['scans'],
           limitations=src['bgs-sobi']['limitations'])

    dh = src['coal-development-high-risk-area']
    q = {'where': '1=1', 'geometry': ','.join(map(str, bbox84)), 'geometryType': 'esriGeometryEnvelope',
         'inSR': 4326, 'spatialRel': 'esriSpatialRelIntersects'}
    count, _ = f.get(dh['service'] + '/query', dict(q, f='json', returnCountOnly='true'), 'dhra-count.json')
    data, entry = f.get(dh['service'] + '/query', dict(q, f='geojson', outFields='FEATURE_TY', outSR=4326,
                                                       resultRecordCount=2000), 'dhra.geojson')
    mining = []
    for feat in data.get('features', []):
        for poly in polygons_of(feat['geometry']):
            clipped = clip_polygon(project_rings(poly, fwd), box)
            if clipped:
                mining.append({'polygon': clipped, 'type': 'development_high_risk_area',
                               'feature_type_as_recorded': (feat.get('properties') or {}).get('FEATURE_TY'),
                               'status': dh['status']})
    ground['mining'] = mining
    record(dh['id'], service=dh['service'], number_matched=count['count'], features_returned=len(data.get('features', [])),
           polygons_in_box=len(mining), raw_sha256=[entry['sha256']], service_crs=dh['service_crs'],
           complete=count['count'] == len(data.get('features', [])),
           limitations=dh['limitations'])

    sp = src['ea-spz-merged']
    feats, matched, shas = ogc_pages(f, sp['service'], {'f': 'application/json', 'bbox': ','.join(map(str, box)),
                                                        'bbox-crs': BNG, 'crs': BNG, 'limit': 500}, 'spz')
    if f.log[-1].get('content_crs', '').strip('<>') != BNG:
        raise RuntimeError('SPZ response not declared EPSG:27700')
    spz = []
    for feat in feats:
        for poly in polygons_of(feat['geometry']):
            clipped = clip_polygon(poly, box)
            if clipped:
                spz.append({'polygon': clipped, 'zone': feat['properties'].get('number'), 'status': sp['status']})
    ground['spz'] = spz
    record(sp['id'], service=sp['service'], number_matched=matched, features_returned=len(feats),
           polygons_in_box=len(spz), raw_sha256=shas,
           complete=matched is None or matched == len(feats), service_crs=sp['service_crs'], limitations=sp['limitations'])

    ground['mine_entries'] = None
    ground['aquifers'] = None
    not_imported = [{'id': s['id'], 'title': s['title'], 'licence': s['licence'], 'verified_url': s['verified_url'],
                     'reason': s.get('finding')} for s in manifest['sources'] if not s['import']]

    doc = {'schema': 'world.ground.v1', 'site': a.site,
           'box': {'e0': box[0], 'n0': box[1], 'e1': box[2], 'n1': box[3]},
           'box_rule': f'e0/n0 {a.e0:.0f}/{a.n0:.0f}, size {a.size:.0f} m, margin {a.margin:.0f} m',
           'crs': 'EPSG:27700 (British National Grid metres)',
           'projection': 'WGS84/CRS84 sources projected with PROJ OSTN15 NTv2 (EPSG op OSGB36 to WGS 84 (9)); '
                         'SPZ served natively in EPSG:27700',
           'clipping': 'Sutherland-Hodgman per ring to the box; clipped rings may run along the box edge',
           'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'layer_semantics': 'null = not imported (licence or no open vector service); [] = queried, none in box',
           'evidence_status': 'All layers are mapped interpretations, index records or modelled regulatory zones. '
                              'None is a measured ground property at cable depth.',
           'sources': sources_out, 'not_imported': not_imported,
           'downloaded_bytes': f.total, 'downloads': f.log, **ground}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(doc, ensure_ascii=False) + '\n')
    with open(cache / 'provenance.json', 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps({'output': str(out), 'downloads': f.log}, indent=2) + '\n')
    print(json.dumps({'output': str(out), 'bedrock': len(ground['bedrock']), 'superficial': len(ground['superficial']),
                      'boreholes': len(bh), 'mining': len(mining), 'spz': len(spz), 'downloaded_bytes': f.total,
                      'borehole_geometry_vs_recorded_max_abs_m': round(worst, 3)}))


if __name__ == '__main__':
    main()
