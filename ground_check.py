"""GPU point-in-polygon over imported ground polygons, witnessed on the CPU.

Seeded points in the ground.json box are classified against every bedrock,
superficial, SPZ and mining polygon twice: a CuPy crossing-number kernel and an
independent NumPy winding-angle sum. Any disagreement fails the run. Also
reports how many points fall in exactly one bedrock polygon (tiling check).
Receipt (LF) is written next to ground.json and under .local/gpu/.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import cupy as cp

ROOT = Path(__file__).parent
KERNEL = cp.RawKernel(r'''extern "C" __global__ void ring(const double* p,int n,const double* r,int m,unsigned char* out){
int i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=n)return;double x=p[2*i],y=p[2*i+1];bool in=false;
for(int k=0,j=m-1;k<m;j=k++){double ax=r[2*j],ay=r[2*j+1],bx=r[2*k],by=r[2*k+1];
double cr=(bx-ax)*(y-ay)-(by-ay)*(x-ax);
if(fabs(cr)<1e-6&&x>=fmin(ax,bx)-1e-9&&x<=fmax(ax,bx)+1e-9&&y>=fmin(ay,by)-1e-9&&y<=fmax(ay,by)+1e-9){out[i]=2;return;}
if((ay>y)!=(by>y)){double at=ax+(y-ay)*(bx-ax)/(by-ay);if(x<at)in=!in;}}out[i]=in?1:0;}''', 'ring')


def gpu_ring(points, ring):
    gp = cp.asarray(points)
    gr = cp.asarray(ring)
    out = cp.empty(len(points), cp.uint8)
    KERNEL(((len(points) + 255) // 256,), (256,), (gp, np.int32(len(points)), gr, np.int32(len(ring)), out))
    return cp.asnumpy(out)


def cpu_ring(points, ring):
    angles = np.zeros(len(points))
    boundary = np.zeros(len(points), bool)
    for a, b in zip(ring, np.roll(ring, -1, axis=0)):
        u = a - points
        v = b - points
        angles += np.arctan2(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0], np.sum(u * v, axis=1))
        cross = (b[0] - a[0]) * (points[:, 1] - a[1]) - (b[1] - a[1]) * (points[:, 0] - a[0])
        boundary |= ((np.abs(cross) < 1e-6) & np.all(points >= np.minimum(a, b) - 1e-9, axis=1)
                     & np.all(points <= np.maximum(a, b) + 1e-9, axis=1))
    return np.where(boundary, 2, (np.abs(angles) > np.pi).astype(np.uint8))


def classify(points, rings, method):
    inside = np.zeros(len(points), bool)
    boundary = np.zeros(len(points), bool)
    for ring in rings:
        r = np.asarray(ring, dtype=np.float64)
        if len(r) < 3 or not np.isfinite(r).all():
            raise ValueError('invalid ring')
        c = method(points, r)
        inside ^= c == 1
        boundary |= c == 2
    return np.where(boundary, 2, inside.astype(np.uint8))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ground', type=Path, default=Path(r'E:\lidar-out\open-land-01\ground.json'))
    ap.add_argument('--points', type=int, default=20000)
    ap.add_argument('--seed', type=int, default=20260926)
    a = ap.parse_args()
    started = time.perf_counter()
    # Fixture: square with square hole; inside, hole, edge, outside.
    fx = np.array([[.5, .5], [2, 2], [0, 1], [5, 5]], dtype=float)
    fr = [[[0, 0], [4, 0], [4, 4], [0, 4]], [[1, 1], [3, 1], [3, 3], [1, 3]]]
    assert classify(fx, fr, gpu_ring).tolist() == classify(fx, fr, cpu_ring).tolist() == [1, 0, 2, 0]

    raw = a.ground.read_bytes()
    g = json.loads(raw)
    b = g['box']
    rng = np.random.default_rng(a.seed)
    points = np.c_[rng.uniform(b['e0'], b['e1'], a.points), rng.uniform(b['n0'], b['n1'], a.points)]
    layers, disagreements, checks = {}, 0, 0
    bedrock_hits = np.zeros(a.points, int)
    for layer in ('bedrock', 'superficial', 'spz', 'mining'):
        rows = g.get(layer)
        if rows is None:
            layers[layer] = 'not imported'
            continue
        out = []
        for row in rows:
            gpu = classify(points, row['polygon'], gpu_ring)
            cpu = classify(points, row['polygon'], cpu_ring)
            bad = int(np.sum(gpu != cpu))
            disagreements += bad
            checks += a.points
            if layer == 'bedrock':
                bedrock_hits += gpu == 1
            out.append({'label': row.get('code') or row.get('zone') or row.get('type'),
                        'inside': int(np.sum(gpu == 1)), 'boundary': int(np.sum(gpu == 2)), 'disagreements': bad})
        layers[layer] = out
    cp.cuda.Stream.null.synchronize()
    receipt = {
        'schema': 'soil.ground_check.v1',
        'device': cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),
        'ground_sha256': hashlib.sha256(raw).hexdigest(), 'box': b,
        'points': a.points, 'seed': a.seed, 'point_polygon_checks': checks,
        'methods': ['CuPy crossing-number kernel (float64)', 'NumPy winding-angle sum (float64)'],
        'gpu_cpu_disagreements': disagreements,
        'bedrock_tiling': {'exactly_one': int(np.sum(bedrock_hits == 1)), 'none': int(np.sum(bedrock_hits == 0)),
                           'more_than_one': int(np.sum(bedrock_hits > 1))},
        'layers': layers, 'elapsed_s': round(time.perf_counter() - started, 3),
        'interpretation': 'Geometric membership of seeded points only. Says nothing about ground properties at depth.'}
    text = json.dumps(receipt, indent=2) + '\n'
    for path in (a.ground.with_name('ground_check_receipt.json'), ROOT / '.local' / 'gpu' / 'ground-checks.json'):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    print(text, end='')
    if disagreements:
        raise SystemExit(f'{disagreements} GPU/CPU disagreements')


if __name__ == '__main__':
    main()
