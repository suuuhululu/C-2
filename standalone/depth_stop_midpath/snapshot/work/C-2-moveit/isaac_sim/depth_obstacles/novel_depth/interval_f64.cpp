// Original float64 slab + per-pixel interval tail. No FMA/fast-math.
#include <cmath>
#include <cstdint>
#include <limits>

static double np_min(double a,double b) {
    if (std::isnan(a)) return a;
    if (std::isnan(b)) return b;
    return a<b?a:b;
}
static double np_max(double a,double b) {
    if (std::isnan(a)) return a;
    if (std::isnan(b)) return b;
    return a>b?a:b;
}
struct Slab {double z,exit,den,de;int64_t axis;};
static Slab slab(const double* low,const double* high,const double* d,const double* de) {
    double entry[3],leave[3];
    for (int i=0;i<3;i++) {
        double a=low[i]/d[i],b=high[i]/d[i];
        entry[i]=np_min(a,b);leave[i]=np_max(a,b);
    }
    int64_t axis=0;double best=entry[0];
    for (int i=1;i<3;i++) {
        if (!std::isnan(best) && (entry[i]>best || std::isnan(entry[i]))) {
            axis=i;best=entry[i];
        }
    }
    return {np_max(np_max(entry[0],entry[1]),entry[2]),
            np_min(np_min(leave[0],leave[1]),leave[2]),d[axis],de[axis],axis};
}
static void planes(const double* size,const double* origin,double* low,double* high) {
    for (int i=0;i<3;i++) {low[i]=-size[i]/2.-origin[i];high[i]=size[i]/2.-origin[i];}
}
extern "C" int slab_f64(const double* size,const double* origin,
        const double* direction,const double* direction_error,int64_t count,
        double* z,double* exit,int64_t* axis,double* den,double* de) {
    if (count<0) return 1;
    double low[3],high[3];planes(size,origin,low,high);
    for (int64_t j=0;j<count;j++) {
        Slab s=slab(low,high,direction+3*j,direction_error+3*j);
        z[j]=s.z;exit[j]=s.exit;axis[j]=s.axis;den[j]=s.den;de[j]=s.de;
    }
    return 0;
}
extern "C" int interval_tail_f64(const double* size,const double* origin,
        const double* direction,const double* direction_error,
        const double* numerator_error,const double* expected_z,
        const int64_t* owner,const int64_t* rows,int64_t row_count,int64_t width,
        int64_t height,int64_t component,int64_t box_index,double near,double far,
        double* nearest,int64_t* face,double* bound) {
    if (row_count<0 || width<=0 || height<=0 || box_index<0 ||
            (component!=0 && component!=2)) return 1;
    for (int64_t r=0;r<row_count;r++)
        if (rows[r]<0 || rows[r]>=height || (r && rows[r]<=rows[r-1])) return 2;
    double low[3],high[3];planes(size,origin,low,high);
    const double tolerance_factor=128.*std::numeric_limits<double>::epsilon();
    for (int64_t r=0;r<row_count;r++) for (int64_t x=0;x<width;x++) {
        int64_t j=r*width+x,g=rows[r]*width+x;
        Slab s=slab(low,high,direction+3*j,direction_error+3*j);
        double err=(numerator_error[s.axis]+std::fabs(s.z)*s.de)/(std::fabs(s.den)-s.de);
        bool visible=s.exit>=s.z && s.z>=near && s.z<=far && owner[j]==component &&
                     std::fabs(s.den)>s.de && std::isfinite(err);
        double tolerance=tolerance_factor*np_max(1.,std::fabs(s.z));
        visible=visible && std::fabs(s.z-expected_z[j])<=tolerance;
        if (visible && s.z<nearest[g]) {
            nearest[g]=s.z;bound[g]=err+tolerance;
            face[g]=box_index*6+s.axis*2+(s.den<0);
        }
    }
    return 0;
}
