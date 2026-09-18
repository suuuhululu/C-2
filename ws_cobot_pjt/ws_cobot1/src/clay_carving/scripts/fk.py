import sys, math, xml.etree.ElementTree as ET
import numpy as np
import os
U=os.path.expanduser("~/collaborative/ws_cobot_pjt/ws_dsr/install/dsr_description2/share/dsr_description2/urdf/m0609.urdf")
root=ET.parse(U).getroot()
joints={}
for j in root.findall("joint"):
    o=j.find("origin"); xyz=[float(v) for v in (o.get("xyz","0 0 0")).split()]; rpy=[float(v) for v in (o.get("rpy","0 0 0")).split()]
    ax=j.find("axis"); axis=[float(v) for v in ax.get("xyz").split()] if ax is not None else [0,0,1]
    joints[j.get("name")]=(j.find("parent").get("link"),j.find("child").get("link"),j.get("type"),xyz,rpy,axis)
def rot(rpy):
    r,p,y=rpy
    Rx=np.array([[1,0,0],[0,math.cos(r),-math.sin(r)],[0,math.sin(r),math.cos(r)]])
    Ry=np.array([[math.cos(p),0,math.sin(p)],[0,1,0],[-math.sin(p),0,math.cos(p)]])
    Rz=np.array([[math.cos(y),-math.sin(y),0],[math.sin(y),math.cos(y),0],[0,0,1]])
    return Rz@Ry@Rx
def axang(a,t):
    a=np.array(a)/np.linalg.norm(a); K=np.array([[0,-a[2],a[1]],[a[2],0,-a[0]],[-a[1],a[0],0]])
    return np.eye(3)+math.sin(t)*K+(1-math.cos(t))*K@K
def T(R,p): M=np.eye(4); M[:3,:3]=R; M[:3,3]=p; return M
def fk(q_deg):
    # chain base_link -> link_6 following joint_1..joint_6
    M=np.eye(4); link="base_link"
    order=[n for n in joints if joints[n][2]=="revolute"]
    for i,n in enumerate(order):
        par,ch,typ,xyz,rpy,axis=joints[n]
        assert par==link,(par,link)
        M=M@T(rot(rpy),xyz)@T(axang(axis,math.radians(q_deg[i])),[0,0,0]); link=ch
    return M,order
def zyz(R):
    # Doosan A,B,C = ZYZ Euler (deg)
    B=math.degrees(math.acos(max(-1,min(1,R[2,2]))))
    if abs(R[2,2])<1-1e-9:
        A=math.degrees(math.atan2(R[1,2],R[0,2])); C=math.degrees(math.atan2(R[2,1],-R[2,0]))
    else:
        A=math.degrees(math.atan2(R[1,0],R[0,0])); C=0.0
    return A,B,C
def report(q,tcp):
    M,order=fk(q); p=M[:3,3]*1000; R=M[:3,:3]
    t=p+R@np.array(tcp)
    return p,t,zyz(R),R
if __name__=="__main__":
    q=[float(v) for v in sys.argv[1:7]]
    for name,tcp in [("flange",(0,0,0)),("v1 (0,0,208)",(0,0,208)),("v3 (0,-60,208)",(0,-60,208))]:
        p,t,abc,R=report(q,tcp)
        print(f"{name:16s} xyz=({t[0]:7.1f},{t[1]:7.1f},{t[2]:7.1f})  ABC=({abc[0]:6.1f},{abc[1]:6.1f},{abc[2]:6.1f})")
    print("tool Z in base:",np.round(R[:,2],3), " tool Y in base:",np.round(R[:,1],3))
