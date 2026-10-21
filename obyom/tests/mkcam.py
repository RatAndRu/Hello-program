# Синтетические кадры → видеофайл для «поддельной камеры» Chromium (e2e.cjs)
import json, sys, numpy as np
from PIL import Image
d = sys.argv[1] if len(sys.argv) > 1 else '/tmp/t/s2'
g = json.load(open(d + '/gt.json')); W, H = g['w'], g['h']
with open('/tmp/t/cam.y4m', 'wb') as f:
    f.write(f'YUV4MPEG2 W{W} H{H} F1:1 Ip A1:1 C420jpeg\n'.encode())
    for fr in g['frames']:
        a = np.asarray(Image.open(d + '/' + fr['file']).convert('YCbCr'))
        f.write(b'FRAME\n'); f.write(a[:, :, 0].tobytes())
        for c in (1, 2): f.write(np.asarray(Image.fromarray(a[:, :, c]).resize((W // 2, H // 2), Image.BILINEAR)).tobytes())
