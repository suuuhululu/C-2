// CPU-only FCL ABI for the offline stop checker. No ROS context or planner.
#include <fcl/fcl.h>
#include <memory>
#include <vector>
using Object=fcl::CollisionObjectd;
extern "C" {
void* stop_mesh(const double* vertices,int count,const int* triangles,int faces) {
 try {
  auto geometry=std::make_shared<fcl::BVHModel<fcl::OBBRSSd>>();
  std::vector<fcl::Vector3d> points;std::vector<fcl::Triangle> indices;
  for(int i=0;i<count;++i)points.emplace_back(vertices[3*i],vertices[3*i+1],vertices[3*i+2]);
  for(int i=0;i<faces;++i)indices.emplace_back(triangles[3*i],triangles[3*i+1],triangles[3*i+2]);
  geometry->beginModel();geometry->addSubModel(points,indices);geometry->endModel();
  return new Object(geometry);
 }catch(...){return nullptr;}
}
void* stop_box(double x,double y,double z) {
 try{return new Object(std::make_shared<fcl::Boxd>(x,y,z));}catch(...){return nullptr;}
}
void stop_transform(void* handle,const double* matrix) {
 auto* object=static_cast<Object*>(handle);fcl::Transform3d t=fcl::Transform3d::Identity();
 for(int i=0;i<3;++i){for(int j=0;j<3;++j)t.linear()(i,j)=matrix[4*i+j];t.translation()[i]=matrix[4*i+3];}
 object->setTransform(t);object->computeAABB();
}
int stop_collide(void* a,void* b) {
 auto* first=static_cast<Object*>(a);auto* second=static_cast<Object*>(b);
 if(!first->getAABB().overlap(second->getAABB()))return 0;
 fcl::CollisionRequestd request;fcl::CollisionResultd result;
 fcl::collide(first,second,request,result);return result.isCollision()?1:0;
}
void stop_destroy(void* handle){delete static_cast<Object*>(handle);}
}
