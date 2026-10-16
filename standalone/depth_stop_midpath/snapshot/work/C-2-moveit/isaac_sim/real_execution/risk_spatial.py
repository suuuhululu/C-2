"""Exact rejection over immutable original AABBs; no geometry approximation.

The hierarchy only rejects. Leaves retain original interval/part indices and
all positives use original bounds. Exact-bit duplicate rows share a query, not
a voxel/representative geometry; their first original point index is retained.
"""
import numpy as np


def build_hierarchy(bounds):
    boxes=bounds.reshape(-1,2,3);nodes=[];enclosures=[];order=[]
    def build(ids):
        index=len(nodes);nodes.append(None)
        enclosure=np.array([boxes[ids,0].min(axis=0),boxes[ids,1].max(axis=0)])
        enclosures.append(enclosure);start=len(order)
        if len(ids)<=16:
            order.extend(ids.tolist());left=right=-1
        else:
            centres=boxes[ids,0]/2+boxes[ids,1]/2
            axis=int(np.argmax(np.ptp(centres,axis=0)))
            ids=ids[np.argsort(centres[:,axis],kind='stable')];mid=len(ids)//2
            left=build(ids[:mid]);right=build(ids[mid:])
        intervals=ids//bounds.shape[1]
        nodes[index]=[left,right,start,len(order),int(intervals.min()),int(intervals.max())]
        return index
    build(np.arange(len(boxes),dtype=np.int64))
    return np.asarray(enclosures),np.asarray(nodes,dtype=np.int64),np.asarray(order,dtype=np.int64)


def validate_hierarchy(bounds,tree,nodes,order):
    """Check every leaf/parent and the complete original-box permutation."""
    boxes=bounds.reshape(-1,2,3);n=len(nodes);ids=np.arange(n)
    if not np.array_equal(np.sort(order),np.arange(len(boxes))) or nodes[0,2]!=0 or nodes[0,3]!=len(boxes):
        raise ValueError('SPATIAL_ORIGINAL_COVERAGE_CHANGED')
    if not np.isfinite(tree).all() or np.any(tree[:,1]<tree[:,0]):raise ValueError('SPATIAL_ENCLOSURE_INVALID')
    leaf=nodes[:,0]==-1;internal=~leaf
    if np.any(nodes[leaf,1]!=-1) or np.any(nodes[internal,:2]<=ids[internal,None]) or np.any(nodes[internal,:2]>=n):
        raise ValueError('SPATIAL_TOPOLOGY_CHANGED')
    l,r=nodes[internal,0],nodes[internal,1]
    if not np.array_equal(np.sort(np.column_stack((l,r)).ravel()),np.arange(1,n)):
        raise ValueError('SPATIAL_CHILD_COVERAGE_CHANGED')
    if (np.any(nodes[l,2]!=nodes[internal,2]) or np.any(nodes[l,3]!=nodes[r,2]) or np.any(nodes[r,3]!=nodes[internal,3]) or
            np.any(nodes[internal,4]!=np.minimum(nodes[l,4],nodes[r,4])) or np.any(nodes[internal,5]!=np.maximum(nodes[l,5],nodes[r,5]))):
        raise ValueError('SPATIAL_CHILD_RANGE_CHANGED')
    if np.any(tree[internal,0]>np.minimum(tree[l,0],tree[r,0])) or np.any(tree[internal,1]<np.maximum(tree[l,1],tree[r,1])):
        raise ValueError('SPATIAL_PARENT_NOT_CONSERVATIVE')
    leaves=np.flatnonzero(leaf);leaves=leaves[np.argsort(nodes[leaves,2])]
    starts=nodes[leaves,2];ends=nodes[leaves,3]
    if starts[0]!=0 or ends[-1]!=len(order) or np.any(ends<=starts) or np.any(ends-starts>16) or np.any(starts[1:]!=ends[:-1]):
        raise ValueError('SPATIAL_LEAF_RANGE_CHANGED')
    source=boxes[order];intervals=order//bounds.shape[1]
    if (np.any(tree[leaves,0]>np.minimum.reduceat(source[:,0],starts,axis=0)) or
            np.any(tree[leaves,1]<np.maximum.reduceat(source[:,1],starts,axis=0)) or
            np.any(nodes[leaves,4]!=np.minimum.reduceat(intervals,starts)) or
            np.any(nodes[leaves,5]!=np.maximum.reduceat(intervals,starts))):
        raise ValueError('SPATIAL_LEAF_NOT_CONSERVATIVE')


def query_hierarchy(bounds,tree,nodes,order,first,partial,current,points,known,errors,low,high,checkpoint,stats):
    """Return (original flat box id or current sentinel, original point id).

    None means no overlap only when checkpoint still reports completion. Caller
    owns the incomplete flag; an interrupted traversal never certifies no-hit.
    """
    count,parts=bounds.shape[:2];original=np.arange(len(points),dtype=np.int64)
    stats.update(input_points=len(points),query_rows=len(points),deduplicated_rows=0,nodes_visited=0,
                 node_point_tests=0,leaf_point_pairs=0)
    if not checkpoint():return None
    if len(points)>256:
        # Raw IEEE bits preserve signed zero and all exact uncertainty values;
        # known/unknown is part of the key, so confidence states cannot merge.
        key=np.column_stack((points.view(np.uint64),errors.view(np.uint64),known.astype(np.uint64)))
        if np.all(key==key[0]):indices=np.array([0],dtype=np.int64)
        else:
            _,indices=np.unique(key,axis=0,return_index=True);indices=np.sort(indices)
        original=original[indices];points=points[indices];known=known[indices];low=low[indices];high=high[indices]
        stats.update(query_rows=len(indices),deduplicated_rows=stats['input_points']-len(indices))
    if not checkpoint():return None
    if not len(points):return None
    def candidates(enclosure,indices):
        kept=[]
        for start in range(0,len(indices),4096):
            if not checkpoint():return None
            ix=indices[start:start+4096]
            stats['node_point_tests']+=len(ix)
            mask=np.all((high[ix]>=enclosure[0])&(low[ix]<=enclosure[1]),axis=1)
            kept.append(ix[mask])
        return np.concatenate(kept) if kept else np.empty(0,dtype=np.int64)
    def exact(box_ids,boxes,indices):
        for start in range(0,len(indices),256):
            if not checkpoint():return None
            ix=indices[start:start+256];p=points[ix]
            stats['leaf_point_pairs']+=len(boxes)*len(ix)
            nominal=np.all((p[None]>=boxes[:,None,0])&(p[None]<=boxes[:,None,1]),axis=2)
            hit=nominal|(known[ix][None]&np.all((high[ix][None]>=boxes[:,None,0])&(low[ix][None]<=boxes[:,None,1]),axis=2))
            if hit.any():
                b,j=np.unravel_index(hit.argmax(),hit.shape)
                if not checkpoint():return None
                return int(box_ids[b]),int(original[ix[j]]),bool(nominal[b,j])
        return None
    all_points=np.arange(len(points),dtype=np.int64)
    # Dynamic partial/current shapes never use unclipped cached leaves.
    for offset,data in ((first*parts,partial),(count*parts,current)):
        if data is None:continue
        for part,box in enumerate(data):
            ix=candidates(box,all_points)
            if ix is None:return None
            result=exact(np.array([offset+part]),box[None],ix)
            if result is not None:return result
    future=first+(partial is not None);stack=[(0,all_points)]
    while stack:
        if not checkpoint():return None
        node,indices=stack.pop();stats['nodes_visited']+=1
        if nodes[node,5]<future:continue
        ix=candidates(tree[node],indices)
        if ix is None:return None
        if not len(ix):continue
        left,right,start,end,_,_=nodes[node]
        if left!=-1:
            stack.append((int(right),ix));stack.append((int(left),ix));continue
        box_ids=order[start:end];box_ids=box_ids[box_ids//parts>=future]
        result=exact(box_ids,bounds.reshape(-1,2,3)[box_ids],ix)
        if result is not None:return result
    return None
