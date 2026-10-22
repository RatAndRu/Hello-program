// Объём v2.8 — C++/WASM ядро: вырезание оболочки (visual hull).
//
// ABI (линейная память WASM):
//   carve_occ(occ, nx, ny, nz, vs, ox, oy, oz, Rb, framesPtr, nFrames,
//             maskBase, alphaBase, frac, few, weakMaj, tfrac, wMean)
//
// FFrameDesc (22 × float32 = 88 байт):
//   0..3  fx, fy, cx, cy
//   4..12 R[3x3], row-major
//   13..15 t[3]
//   16    rms
//   17..18 w, h (как float)
//   19    maskOff  (uint32, в байтах от maskBase)
//   20    alphaOff (uint32, в байтах от alphaBase; 0 если нет)
//   21    wF (нормализованный вес кадра)
//   22    trusted (float 1/0)

#include <emscripten.h>
#include <math.h>
#include <string.h>

static inline float myfmax(float a, float b) { return a > b ? a : b; }
static inline unsigned u32f(const float* p) { unsigned v; memcpy(&v, p, 4); return v; }

static inline float softAt(const unsigned char* mask, const unsigned char* alpha, int idx) {
  unsigned char m = mask[idx];
  if (m == 0) return 0.f;
  if ((m == 1 || m == 2) && alpha && alpha[idx] < 255) return alpha[idx] / 255.f;
  if (m == 3) return 0.5f;
  return 1.f;
}

static inline int projectVoxel(const float* f, float X, float Y, float Z, float* uf, float* vf) {
  const float* R = f+4; const float* t = f+13;
  float cz = R[6]*X + R[7]*Y + R[8]*Z + t[2];
  if (cz <= 1.f) return 0;
  *uf = f[0]*(R[0]*X + R[1]*Y + R[2]*Z + t[0])/cz + f[2];
  *vf = f[1]*(R[3]*X + R[4]*Y + R[5]*Z + t[1])/cz + f[3];
  int w = (int)f[17], h = (int)f[18];
  int iu = (int)*uf, iv = (int)*vf;
  return (iu >= 0 && iv >= 0 && iu < w && iv < h);
}

EMSCRIPTEN_KEEPALIVE
void carve_occ(float* occ,
               int nx, int ny, int nz, float vs,
               float ox, float oy, float oz, float Rb,
               const float* frames, int nFrames,
               const unsigned char* maskBase, const unsigned char* alphaBase,
               float frac, int few, float weakMaj, float tfrac,
               float wMean) {
  for (int z = 0; z < nz; z++) {
    float Z = oz + z * vs;
    for (int y = 0; y < ny; y++) {
      float Y = oy + y * vs;
      for (int x = 0; x < nx; x++) {
        float X = ox + x * vs;
        int vi = (z*ny + y)*nx + x;
        if (X*X + Y*Y > Rb*Rb) { occ[vi] = 0.f; continue; }
        float bg = 0.f, weak = 0.f, seen = 0.f;
        int nbg = 0, nwk = 0, left = nFrames;
        float tbg = 0.f; int tseen = 0;
        for (int k = 0; k < nFrames; k++, left--) {
          const float* f = frames + k*22;
          unsigned mOff = u32f(f+19), aOff = u32f(f+20);
          const unsigned char* mask = maskBase + mOff;
          const unsigned char* alpha = aOff ? (alphaBase + aOff) : (const unsigned char*)0;
          int w = (int)f[17], h = (int)f[18];
          float uf, vf;
          if (!projectVoxel(f, X, Y, Z, &uf, &vf)) continue;
          int iu = (int)uf, iv = (int)vf;
          int idx = iv*w + iu;
          unsigned char mv = mask[idx];
          if (mv == 4) continue;
          if ((mv == 1 || mv == 2) && alpha && alpha[idx] < 255 && iu > 0 && iv > 0 && iu < w-2 && iv < h-2) {
            float uu = uf - 0.5f, vv = vf - 0.5f;
            int i0 = (int)uu, j0 = (int)vv;
            float a = uu - i0, b = vv - j0;
            int q = j0*w + i0;
            float sv = (1-a)*(1-b)*softAt(mask, alpha, q)
                     + a*(1-b)*softAt(mask, alpha, q+1)
                     + (1-a)*b*softAt(mask, alpha, q+w)
                     + a*b*softAt(mask, alpha, q+w+1);
            if (sv < 0.5f) mv = 0;
          }
          float wk = f[21];
          int trusted = (f[22] >= 0.5f);
          seen += wk;
          if (mv == 0) { bg += wk; nbg++; nwk++; if (trusted) { tseen++; tbg += wk; } }
          else if (mv == 3) { weak += wk; nwk++; }
          else if (trusted) tseen++;
          if (!few && nbg >= 3 && bg >= frac * (seen + left - 1)) break;
        }
        int need_bg = few ? 1 : 3;
        int trustCut = (tseen >= 3 && tbg >= myfmax(2.f, tfrac * tseen));
        int cut;
        if (seen < 3 * wMean) cut = 1;
        else if (few) cut = (nbg >= 1) ? 1 : 0;
        else {
          int c1 = (nbg >= need_bg && bg >= frac * seen);
          int c2 = (nwk > 0 && (bg+weak) >= myfmax(2.f*wMean, frac*seen) && (bg+weak) >= weakMaj * seen);
          cut = c1 || c2;
        }
        occ[vi] = (trustCut || cut) ? 0.f : 1.f;
      }
    }
  }
}
