// Exact original NumPy bounding-box fragment arithmetic; no geometry changes.
#include <cmath>
#include <cstdint>
#include <limits>
extern "C" int raster_bbox_f64(const double* uv, const double* inverse_z,
    const std::int64_t* low, const std::int64_t* high,
    std::int64_t count, std::int64_t height, std::int64_t width, double* buffer) {
    if (count < 0 || height <= 0 || width <= 0) return -1;
    for (std::int64_t i = 0; i < count; ++i) {
        const auto x0 = low[2*i], y0 = low[2*i+1];
        const auto x1 = high[2*i], y1 = high[2*i+1];
        if (x0 < 0 || y0 < 0 || x1 >= width || y1 >= height) return -2;
        const double ax=uv[6*i], ay=uv[6*i+1];
        const double bx=uv[6*i+2], by=uv[6*i+3];
        const double cx=uv[6*i+4], cy=uv[6*i+5];
        const double det=(by-cy)*(ax-cx)+(cx-bx)*(ay-cy);
        if (!(std::abs(det) > std::numeric_limits<double>::epsilon())) continue;
        for (auto y=y0; y<=y1; ++y) {
            for (auto x=x0; x<=x1; ++x) {
                const double wa=((by-cy)*(double(x)-cx)+(cx-bx)*(double(y)-cy))/det;
                const double wb=((cy-ay)*(double(x)-cx)+(ax-cx)*(double(y)-cy))/det;
                const double wc=(1.0-wa)-wb;
                if (!(wa>=-1e-12 && wb>=-1e-12 && wc>=-1e-12)) continue;
                const double denominator=(wa*inverse_z[3*i]+wb*inverse_z[3*i+1])+wc*inverse_z[3*i+2];
                const double z=1.0/denominator;
                auto& current=buffer[y*width+x];
                // np.minimum.at propagates an existing NaN, otherwise selects
                // incoming NaN or <= value (including signed-zero ties).
                if (!std::isnan(current) && (std::isnan(z) || z<=current)) current=z;
            }
        }
    }
    return 0;
}
