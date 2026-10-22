// v2.8 C++/WASM core (Emscripten) — hot loop of visual-hull carving.
// Function: carve_occ — for each voxel, project into all frames and tally mask votes.
// ABI kept tiny on purpose; JS wrapper passes flattened Float32 arrays for per-frame pose/mask
// metadata and receives mutated occ[] (0 = carved, 1 = kept). JS fallback exists in recon.js.
//
// Per-frame packed layout (float32):
//   fx, fy, cx, cy, R[9], t[3], rms, w, h, offset_in_u8_mask, trusted
//   → stride 4+9+3+1+1+1+1+1 = 21 floats per frame
// Mask is one shared Uint8Array (passed as HEAPU8 view at maskOff offset).

#include <emscripten.h>
#include <math.h>

EMSCRIPTEN_KEEPALIVE
void carve_occ(float* occ,                                     // nx*ny*nz float 0..1 (output)
               int nx, int ny, int nz, float vs,
               float ox, float oy, float oz, float Rb,
               float* frames, int nFrames,
               unsigned char* masks,
               float frac, int few, float weakMaj,
               int zFrom, int zTo) {
  for (int z = zFrom; z < zTo; z++) {
    float Z = oz + z * vs;
    for (int y = 0; y < ny; y++) {
      float Y = oy + y * vs;
      for (int x = 0; x < nx; x++) {
        float X = ox + x * vs;
        if (X*X + Y*Y > Rb*Rb) { occ[(z*ny + y)*nx + x] = 0; continue; }
        float bg = 0, weak = 0, seen = 0; int nbg = 0;
        int left = nFrames;
        for (int k = 0; k < nFrames; k++, left--) {
          float* f = frames + k*21;
          float fx = f[0], fy = f[1], cx = f[2], cy = f[3];
          float* R = f+4; float* t = f+13;
          float cz = R[6]*X + R[7]*Y + R[8]*Z + t[2];
          if (cz <= 1.f) continue;
          float u = fx*(R[0]*X + R[1]*Y + R[2]*Z + t[0])/cz + cx;
          float v = fy*(R[3]*X + R[4]*Y + R[5]*Z + t[1])/cz + cy;
          int iu = (int)u, iv = (int)v;
          int w = (int)f[18], h = (int)f[19];
          if (iu < 0 || iv < 0 || iu >= w || iv >= h) continue;
          int mo = (int)f[20];
          unsigned char mv = masks[mo + iv*w + iu];
          if (mv == 4) continue;
          float wk = 1.f; // simple weight in v1
          seen += wk;
          if (mv == 0) { bg += wk; nbg++; }
          else if (mv == 3) weak += wk;
          if (!few && nbg >= 2 && bg >= frac*(seen+left-1)) break;
        }
        float need = few ? 1 : (nbg >= 2 ? fmaxf(2, frac*seen) : 1e9f);
        int cut = (seen < 3) ? 1 : (few ? nbg >= 1 : (nbg>=2 && bg >= frac*seen) || (bg+weak >= fmaxf(2,frac*seen) && bg+weak >= weakMaj*seen && nbg+weak>0));
        occ[(z*ny+y)*nx+x] = cut ? 0.f : 1.f;
      }
    }
  }
}
