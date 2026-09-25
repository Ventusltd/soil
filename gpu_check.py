"""Bounded double-precision GPU screening of imported conservation polygons.
Independent CPU winding-angle witness; no restoration score or land judgement.
"""
import json,hashlib,time
from pathlib import Path
import numpy as np
import cupy as cp
from thermal import conductivity_to_resistivity
ROOT=Path(__file__).parent;OUT=ROOT/'.local'/'gpu';OUT.mkdir(parents=True,exist_ok=True)
kernel=cp.RawKernel(r'''extern "C" __global__ void ring(const double* p,int n,const double* r,int m,unsigned char* result){int i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=n)return;double x=p[2*i],y=p[2*i+1];bool in=false;for(int k=0,j=m-1;k<m;j=k++){double ax=r[2*j],ay=r[2*j+1],bx=r[2*k],by=r[2*k+1];double cr=(bx-ax)*(y-ay)-(by-ay)*(x-ax);if(fabs(cr)<1e-12&&x>=fmin(ax,bx)-1e-12&&x<=fmax(ax,bx)+1e-12&&y>=fmin(ay,by)-1e-12&&y<=fmax(ay,by)+1e-12){result[i]=2;return;}if((ay>y)!=(by>y)){double at=ax+(y-ay)*(bx-ax)/(by-ay);if(x<at)in=!in;}}result[i]=in?1:0;}''','ring')
def classify(points,ring):
    r=np.asarray(ring,dtype=np.float64)[:,:2]
    if np.array_equal(r[0],r[-1]):r=r[:-1]
    if len(r)<3 or not np.isfinite(r).all():raise ValueError('Invalid ring')
    gp=cp.asarray(points);gr=cp.asarray(r);out=cp.empty(len(points),cp.uint8)
    kernel(((len(points)+255)//256,),(256,),(gp,np.int32(len(points)),gr,np.int32(len(r)),out))
    angles=np.zeros(len(points));boundary=np.zeros(len(points),bool)
    for a,b in zip(r,np.roll(r,-1,axis=0)):
        u=a-points;v=b-points;angles+=np.arctan2(u[:,0]*v[:,1]-u[:,1]*v[:,0],np.sum(u*v,axis=1))
        cross=(b[0]-a[0])*(points[:,1]-a[1])-(b[1]-a[1])*(points[:,0]-a[0])
        boundary|=(np.abs(cross)<1e-12)&np.all(points>=np.minimum(a,b)-1e-12,axis=1)&np.all(points<=np.maximum(a,b)+1e-12,axis=1)
    witness=np.where(boundary,2,(np.abs(angles)>np.pi).astype(np.uint8))
    actual=cp.asnumpy(out);assert np.array_equal(actual,witness),int(np.sum(actual!=witness))
    return actual
def polygon(points,rings):
    inside=np.zeros(len(points),bool);boundary=np.zeros(len(points),bool)
    for ring in rings:
        c=classify(points,ring);inside^=c==1;boundary|=c==2
    return np.where(boundary,2,inside.astype(np.uint8))
started=time.perf_counter()
fixture=polygon(np.array([[.5,.5],[2,2],[0,1],[5,5]],dtype=float),[[[0,0],[4,0],[4,4],[0,4],[0,0]],[[1,1],[3,1],[3,3],[1,3],[1,1]]])
assert fixture.tolist()==[1,0,2,0]
path=ROOT/'.local'/'environment'/'sssi.geojson';raw=path.read_bytes();geo=json.loads(raw)
provenance=json.loads((path.parent/'provenance.json').read_text());west,south,east,north=provenance['bbox_wgs84']
x=np.linspace(west,east,256);y=np.linspace(south,north,256);xx,yy=np.meshgrid(x,y);points=np.c_[xx.ravel(),yy.ravel()]
records=[];masks=[]
for f in geo['features']:
    geom=f['geometry'];polys=[geom['coordinates']] if geom['type']=='Polygon' else geom['coordinates'] if geom['type']=='MultiPolygon' else None
    if polys is None:raise ValueError('Unsupported geometry')
    interior=np.zeros(len(points),bool);boundary=np.zeros(len(points),bool)
    for poly in polys:
        c=polygon(points,poly);interior|=c==1;boundary|=c==2
    mask=np.where(boundary,2,interior.astype(np.uint8));masks.append(mask)
    records.append({'feature_id':f.get('id'),'inside_points':int(np.sum(mask==1)),'boundary_points':int(np.sum(mask==2)),'polygons':len(polys)})
k=[.25,.5,1,2,4];gpu_rho=cp.asnumpy(1/cp.asarray(k,dtype=cp.float64));assert np.array_equal(gpu_rho,np.array(conductivity_to_resistivity(k)))
cp.cuda.Stream.null.synchronize()
result={'device':cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),'source_sha256':hashlib.sha256(raw).hexdigest(),'bbox_wgs84':provenance['bbox_wgs84'],'points_per_feature':len(points),'feature_point_checks':len(points)*len(records),'features':records,'gpu_cpu_disagreements':0,'thermal_reciprocal_fixture':'5 synthetic unit checks only; not site thermal measurements','elapsed_s':time.perf_counter()-started,'interpretation':'Geometric conservation-context membership only. Does not assess habitat condition, suitability, cable ampacity or soil thermal resistivity.'}
np.savez_compressed(OUT/'environment-mask.npz',longitude=x,latitude=y,classifications=np.array(masks))
(OUT/'checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
