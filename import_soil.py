"""Bounded UKCEH metadata import; measurements remain explicitly pending.

Default output: .local/soil/provenance.json and catalogue.json.
No third-party dependencies. No fabricated geometry or thermal resistivity.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / '.local/soil')
    parser.add_argument('--offline', action='store_true', help='Record verified source manifest without a network request')
    args = parser.parse_args()
    source = json.loads(Path(__file__).with_name('soil_sources.json').read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=True)
    result = {'source': source, 'retrieved_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'status': 'blocked_measurements_not_downloaded', 'numeric_output': None, 'row_count': 0}
    if not args.offline:
        url = source['catalogue_url'] + '?format=json'
        # Bound the read and reject truncation; the metadata is normally about 10 KB.
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(262144)
            if len(raw) == 262144:
                raise RuntimeError('Metadata reaches 256 KiB cap; refusing a potentially truncated record')
            metadata = json.loads(raw)
            if metadata.get('id') != '8c87a397-a010-48a4-8ca5-0f3742c2d857':
                raise RuntimeError('Unexpected UKCEH record')
        (args.output / 'catalogue.json').write_bytes(raw)
        result['metadata'] = {'url': url, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    else:
        result['status'] = 'offline_manifest_only_measurements_pending'
    (args.output / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'output': str(args.output), 'numeric_output': None}))


if __name__ == '__main__':
    main()
