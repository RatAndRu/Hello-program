// Объём v2.8 — C++/WASM ядро: вырезание оболочки (visual hull).
// Полный аналог JS-цикла в recon.js: взвешенное голосование по кадрам, субпиксельная кромка
// через edge-alpha, доверенные кадры, досрочный выход.
//
// Структура кадра (упакована как Float32, floatsPerFrame = 24):
//   0:fx 1:fy 2:cx 3:cy
//   4..12: R (row-major 3x3)
//   13..15: t
//   16: rms (вес = 1/(1+max(0,rms-1)^2) вычисляется в JS)
//   17: w  18: h
//   19: maskByteOffset (HEAPU8, абсолютное смещение)
//   20: alphaByteOffset (HEAPU8, абсолютное смещение; 0 если нет alpha)
//   21: wF (вес кадра, нормализованный)
//   22: trusted (1 или 0)
//   23: __padding
//
// Маска: Uint8, значения 0/1/2/3/4 (см. recon.js).
// Alpha: Uint8, 0..255, доля предмета на кромке (edgeAlpha).
//
// Вызывающий из JS (wasmcarve.js) упаковывает все кадры в один HEAPF32 и копирует
// маски/альфы в один непрерывный HEAPU8, передавая абсолютные смещения.

#include <emscripten.h>
#include <math.h>

static inline float softAt(const unsigned char* mask, const unsigned char* alpha, int w, int h, int idx) {
  unsigned char m = mask[idx];
  if (m == 0) return 0.f;
  if ((m == 1 || m == 2) && alpha && alpha[idx] < 255) return alpha[idx] / 255.f;
  if (m == 3) return 0.5f;
  return 1.f;
}

// Проекция вокселя (X,Y,Z) камерой f; возвращает 0 если воксель за камерой/вне кадра, 1 если внутри; *uf/*vf — пиксельные координаты
static inline int projectVoxel(const float* f, float X, float Y, float Z, float* uf_out, float* vf_out) {
  const float* R = f+4; const float* t = f+13;
  float cz = R[6]*X + R[7]*Y + R[8]*Z + t[2];
  if (cz <= 1.f) return 0;
  float u = f[0]*(R[0]*X + R[1]*Y + R[2]*Z + t[0])/cz + f[2];
  float v = f[1]*(R[3]*X + R[4]*Y + R[5]*Z + t[1])/cz + f[3];
  *uf_out = u; *vf_out = v;
  int w = (int)f[17], h = (int)f[18];
  int iu = (int)u, iv = (int)v;
  if (iu < 0 || iv < 0 || iu >= w || iv >= h) return 0;
  return 1;
}

EMSCRIPTEN_KEEPALIVE
void carve_occ(float* occ,                                     // nx*ny*nz float 0..1 (output)
               int nx, int ny, int nz, float vs,
               float ox, float oy, float oz, float Rb,
               float* frames, int nFrames,
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
        int nbg = 0, nwk = 0; // nwk = nbg+weak (для штучного порога)
        float tbg = 0.f; int tseen = 0;
        int left = nFrames;
        for (int k = 0; k < nFrames; k++, left--) {
          const float* f = frames + k*24;
          const unsigned char* mask = maskBuf + ((int)f[19]);
          const unsigned char* alpha = ((int)f[20]) ? (alphaBuf ? alphaBuf + ((int)f[20]) : 0) : 0;
          int w = (int)f[17], h = (int)f[18];
          float uf, vf;
          if (!projectVoxel(f, X, Y, Z, &uf, &vf)) continue;
          int iu = (int)uf, iv = (int)vf;
          int idx = iv*w + iu;
          unsigned char mv = mask[idx];
          if (mv == 4) continue; // в цилиндре не видно
          // субпиксельная кромка
          if ((mv == 1 || mv == 2) && alpha && alpha[idx] < 255 && iu > 0 && iv > 0 && iu < w-2 && iv < h-2) {
            float uu = uf - 0.5f, vv = vf - 0.5f;
            int i0 = (int)uu, j0 = (int)vv;
            float a = uu - i0, b = vv - j0;
            int q = j0*w + i0;
            float sv = (1-a)*(1-b)*softAt(mask, alpha, w, h, q)
                     + a*(1-b)*softAt(mask, alpha, w, h, q+1)
                     + (1-a)*b*softAt(mask, alpha, w, h, q+w)
                     + a*b*softAt(mask, alpha, w, h, q+w+1);
            if (sv < 0.5f) mv = 0;
          }
          float wk = f[21]; // wF[k]
          seen += wk;
          if (mv == 0) { bg += wk; nbg++; nwk++; }
          else if (mv == 3) { weak += wk; nwk++; }
          int trusted = (int)f[22];
          if (trusted) { tseen++; if (mv == 0) tbg += wk; }
          // досрочный выход
          if (!few && nbg >= 2 && bg >= frac * (seen + left - 1)) break;
        }
        int trustCut = (tseen >= 3 && tbg >= fmaxf(2.f, tfrac * tseen));
        int cut;
        if (seen < 3 * wMean) cut = 1;
        else if (few) cut = (nbg >= 1) ? 1 : 0;
        else {
          int c1 = (nbg >= 2 && bg >= frac * seen);
          int c2 = (nwk > 0 && (bg+weak) >= fmaxf(2.f*wMean, frac*seen) && (bg+weak) >= weakMaj * seen);
          cut = c1 || c2;
        }
        occ[vi] = (trustCut || cut) ? 0.f : 1.f;
      }
    }
  }
}
