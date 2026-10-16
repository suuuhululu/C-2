"""Fail-closed continuous tool-axis certificate on delivered quintic intervals.

Directed Decimal interval FK anchors plus exact rational Bernstein angular-rate
bounds. No sampled-only acceptance, acceptance slack, SDK or device access.
"""
from decimal import Context,Decimal,ROUND_FLOOR,ROUND_CEILING
from fractions import Fraction as F
from math import comb,factorial
import xml.etree.ElementTree as ET
from stop_curve import quintic_intervals
from plan_only import JOINTS

LO=Context(prec=40,rounding=ROUND_FLOOR);HI=Context(prec=40,rounding=ROUND_CEILING)

def iv(x):
    if isinstance(x,tuple):return x
    x=F(x);a,b=Decimal(x.numerator),Decimal(x.denominator)
    return LO.divide(a,b),HI.divide(a,b)
def add(a,b):return LO.add(a[0],b[0]),HI.add(a[1],b[1])
def neg(a):return a[1].copy_negate(),a[0].copy_negate()
def sub(a,b):return add(a,neg(b))
def mul(a,b):
    if a==iv(0) or b==iv(0):return iv(0)
    if a==iv(1):return b
    if b==iv(1):return a
    return min(LO.multiply(x,y) for x in a for y in b),max(HI.multiply(x,y) for x in a for y in b)
def div(a,b):
    if b[0]<=0<=b[1]:raise ValueError('AXIS_INTERVAL_ZERO_DIVISOR')
    return mul(a,(LO.divide(Decimal(1),b[1]),HI.divide(Decimal(1),b[0])))
def sincos(x):
    if x==(Decimal(0),Decimal(0)):return iv(0),iv(1)
    bound=max(x[0].copy_abs(),x[1].copy_abs())
    if bound>8:raise ValueError('AXIS_ANCHOR_ANGLE_RANGE_UNSUPPORTED')
    if bound>Decimal('3.2'):
        # Any integer reduction is valid; this enclosed pi preserves identity.
        pi=Decimal('3.14159265358979323846264338327950288419716939937510')
        period=mul(iv(2),(pi,HI.add(pi,Decimal('1e-50'))))
        k=round(float(x[0])/6.283185307179586);x=sub(x,mul(iv(k),period))
        bound=max(x[0].copy_abs(),x[1].copy_abs())
        if bound>4:raise ValueError('AXIS_RANGE_REDUCTION_UNRESOLVED')
    square=mul(x,x);s=term_s=x;c=term_c=iv(1)
    for k in range(1,16):
        term_s=neg(div(mul(term_s,square),iv((2*k)*(2*k+1))))
        term_c=neg(div(mul(term_c,square),iv((2*k-1)*(2*k))))
        s=add(s,term_s);c=add(c,term_c)
    def widen(value,order):
        remainder=HI.divide(HI.power(bound,order),Decimal(factorial(order)))
        return LO.subtract(value[0],remainder),HI.add(value[1],remainder)
    return widen(s,33),widen(c,32)
def matrix_product(a,b):
    return [[sum_iv([mul(a[i][k],b[k][j]) for k in range(3)]) for j in range(3)] for i in range(3)]
def sum_iv(values):
    result=iv(0)
    for v in values:result=add(result,v)
    return result
def identity():return [[iv(int(i==j)) for j in range(3)] for i in range(3)]
def rotation(axis,angle):
    if sum(v*v for v in axis)!=1:raise ValueError('AXIS_GATE_REQUIRES_EXACT_UNIT_JOINT_AXIS')
    s,c=sincos(angle);one_minus=sub(iv(1),c)
    skew=[[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]]
    return [[add(add(mul(iv(int(i==j)),c),mul(iv(axis[i]*axis[j]),one_minus)),mul(iv(skew[i][j]),s)) for j in range(3)] for i in range(3)]
def chain(robot,tcp):
    parents={j.find('child').get('link'):j for j in robot.findall('joint')};result=[];node=tcp
    while node!='base_link':
        j=parents[node];origin=j.find('origin');rpy=[F(float(x)) for x in (origin.get('rpy','0 0 0') if origin is not None else '0 0 0').split()]
        local=identity()
        for axis,angle in zip(([1,0,0],[0,1,0],[0,0,1]),rpy):local=matrix_product(rotation(axis,iv(angle)),local)
        if j.get('type') not in ('fixed','revolute') or j.find('mimic') is not None:raise ValueError('AXIS_TOOL_CHAIN_KIND_UNSUPPORTED')
        name=j.get('name')
        if j.get('type')=='revolute' and name not in JOINTS:raise ValueError('AXIS_TOOL_CHAIN_HAS_NONARM_MOTION')
        axis=[F(float(x)) for x in j.find('axis').get('xyz').split()] if j.get('type')=='revolute' else None
        result.append((local,name,axis));node=j.find('parent').get('link')
    return result[::-1]
def polynomial(c,u):
    result=F(0)
    for v in c[::-1]:result=result*u+v
    return result
def derivative_bound(c,a,b):
    # Power -> Bernstein on the exact subinterval. Convex hull bounds all u.
    d=[(i+1)*c[i+1] for i in range(5)];width=b-a
    power=[sum((d[i]*comb(i,k)*a**(i-k)*width**k for i in range(k,5)),F(0)) for k in range(5)]
    controls=[sum((power[j]*F(comb(k,j),comb(4,j)) for j in range(k+1)),F(0)) for k in range(5)]
    return max(map(abs,controls))

def certify_axis(trajectory,robot_description,tcp,world_axis,*,limit_rad=.15,max_cells=50000,max_depth=18):
    if limit_rad!=.15:raise ValueError('ORIGINAL_AXIS_LIMIT_0_15_REQUIRED')
    robot=ET.fromstring(robot_description);links=chain(robot,tcp);axis=[iv(float(x)) for x in world_axis]
    length2=sum_iv([mul(x,x) for x in axis])
    if length2[0]<=0:raise ValueError('POSITIVE_WORLD_AXIS_REQUIRED')
    # Decimal.sqrt is correctly rounded half-even; next representables enclose it.
    norm=(LO.next_minus(LO.sqrt(length2[0])),HI.next_plus(HI.sqrt(length2[1])))
    axis=[div(x,norm) for x in axis];cap=F(limit_rad);checked=0;certified=0;deepest=0
    def anchor(coeff,u):
        q={n:iv(polynomial(c,u)) for n,c in zip(JOINTS,coeff)};v=[iv(0),iv(0),iv(1)]
        def apply(r,v):return [sum_iv([mul(r[i][j],v[j]) for j in range(3)]) for i in range(3)]
        for local,name,direction in links[::-1]:
            if direction is not None:v=apply(rotation(direction,q[name]),v)
            v=apply(local,v)
        return sum_iv([mul(v[i],axis[i]) for i in range(3)])
    cos_limit=sincos(iv(cap))[1]
    for start,h,coefficients in quintic_intervals(trajectory):
        coeff=[[F(float(x)) for x in coefficients[:,j]] for j in range(6)];pending=[(F(0),F(1),0)]
        while pending:
            a,b,depth=pending.pop();checked+=1;deepest=max(deepest,depth)
            if checked>max_cells:raise ValueError('AXIS_CERTIFICATE_WORK_BOUND_UNRESOLVED')
            mid=(a+b)/2;dot=anchor(coeff,mid)
            if dot[1]<cos_limit[0]:raise ValueError(f'ORIGINAL_PATH_AXIS_VIOLATION interval={start} u={float(mid)}')
            angular_change=sum((derivative_bound(c,a,b) for c in coeff),F(0))*(b-a)/2
            remaining=cap-angular_change
            if remaining>=0 and dot[0]>=sincos(iv(remaining))[1][1]:certified+=1;continue
            if depth>=max_depth:raise ValueError(f'AXIS_CERTIFICATE_UNRESOLVED interval={start}')
            pending.extend([(a,mid,depth+1),(mid,b,depth+1)])
    return dict(scope='FINAL_QUINTIC_CONTINUOUS_AXIS_CERTIFICATE_NOT_COLLISION_OR_NATIVE_PROOF',limit_rad=.15,
        method='DIRECTED_DECIMAL_TAYLOR_INTERVAL_FK_ANCHOR_PLUS_EXACT_RATIONAL_BERNSTEIN_ANGULAR_RATE',
        cells_evaluated=checked,cells_certified=certified,max_depth=deepest,sampled_only_acceptance=False,acceptance_slack_rad=0,
        precision_decimal_digits=40,tool_axis=[0,0,1],world_axis=world_axis)
