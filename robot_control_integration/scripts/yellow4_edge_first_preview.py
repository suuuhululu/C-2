"""Preview coupled TCP rotation/translation for one yellow 4-stud block; no devices."""
import argparse,json,sys
from pathlib import Path
NATIVE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(NATIVE))
from app.edge_first_seating import preview


def save_plot(previews,path):
    """Static scientific diagram; importing plotting libraries never opens a device."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig=plt.figure(figsize=(7*len(previews),6))
    for panel,result in enumerate(previews,1):
        if result.get('schema_version')!='yellow4-pivot-preview-result/2':
            raise ValueError('BLOCK_AND_GRASP_DIAGRAM_REQUIRES_V2_CONFIG')
        ax=fig.add_subplot(1,len(previews),panel,projection='3d')
        points=result['waypoints'];tcp=np.array([p['tcp_mm_zyz_deg'][:3] for p in points])
        line=np.array(result['contact_line_points_mm']);studs=np.array(result['target_stud_centers_mm'])
        ax.plot(*tcp.T,color='#1565c0',linewidth=2.5,label='TCP orbit')
        ax.scatter(*tcp[[0,-1]].T,color=['#ef6c00','#00897b'],s=35)
        ax.scatter(*studs.T,color='#388e3c',s=65,marker='o',label='Target stud centers')
        indices=sorted({0,len(points)//2,len(points)-1})
        colors=['#ef6c00','#8e24aa','#00897b']
        edges=[(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
        for i in indices:
            color=colors[0] if i==0 else colors[2] if i==len(points)-1 else colors[1]
            corners=np.array(points[i]['block_corners_mm'])
            for j,(a,b) in enumerate(edges):
                ax.plot(*corners[[a,b]].T,color=color,alpha=.85,
                    label=f"Block: {points[i]['tilt_deg']:+.1f} deg" if j==0 else None)
            ax.add_collection3d(Poly3DCollection([corners[4:]],facecolor=color,alpha=.10))
            # Show the rigid grasp lever arm, not a second independently rotating tool.
            ax.plot(*np.stack((tcp[i],np.mean(corners[:4],axis=0))).T,color=color,linestyle=':',alpha=.7)
        ax.plot(*line.T,color='#c62828',linewidth=4,linestyle='--',
                marker='x',markersize=9,label='Assumed fixed contact axis')
        all_points=np.concatenate((tcp,line,studs,*[np.array(p['block_corners_mm']) for p in points]))
        center=(all_points.min(axis=0)+all_points.max(axis=0))/2
        half=max(float(np.ptp(all_points,axis=0).max())/2,1.)*1.12
        ax.set_xlim(center[0]-half,center[0]+half)
        ax.set_ylim(center[1]-half,center[1]+half)
        ax.set_zlim(center[2]-half,center[2]+half);ax.set_box_aspect((1,1,1))
        ax.set_xlabel('X (mm)');ax.set_ylabel('Y (mm)');ax.set_zlabel('Z (mm)')
        ax.view_init(elev=23,azim=-57)
        ax.set_title(f"{result['operation'].upper()}: {points[0]['tilt_deg']:+.1f} -> {points[-1]['tilt_deg']:+.1f} deg\n"
                     f"Frame: {result['coordinate_frame']}",fontsize=10)
        ax.legend(loc='upper left',fontsize=8)
    source='SYNTHETIC EXAMPLE' if all('SYNTHETIC' in p['source_kind'] for p in previews) else 'INPUT GEOMETRY'
    fig.suptitle(f'Yellow 2x2 | {source} | Geometry only; no robot commands',fontsize=13)
    fig.text(.5,.025,'Fixed-axis rigid-grasp hypothesis. Stud engagement / release and collisions are NOT verified.',ha='center',fontsize=10)
    fig.subplots_adjust(left=.025,right=.97,bottom=.1,top=.84,wspace=.02)
    path.parent.mkdir(parents=True,exist_ok=True);fig.savefig(path,dpi=150);plt.close(fig)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=NATIVE/'fixtures/yellow4_edge_first_preview.json')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--operation',choices=('assembly','removal','both'))
    parser.add_argument('--plot',type=Path,help='Save a v2 geometry diagram (PNG/SVG); no live popup.')
    args=parser.parse_args(argv)
    config=json.loads(args.config.read_text())
    if args.operation=='both':
        results=[preview(config,operation) for operation in ('assembly','removal')]
        result=dict(operation_previews={p['operation']:p for p in results},physical_commands=0,execution_allowed=False)
    else:
        result=preview(config,args.operation);results=[result]
    if args.plot:save_plot(results,args.plot)
    text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(text,end='');return 0


if __name__=='__main__':raise SystemExit(main())
