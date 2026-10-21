import sys, glob, numpy as np
from PIL import Image
d, W = sys.argv[1], int(sys.argv[2])
for f in sorted(glob.glob(d + '/f*.jpg')):
    im = Image.open(f).convert('RGBA'); h = round(im.height * W / im.width)
    np.asarray(im.resize((W, h), Image.BILINEAR)).tofile(f[:-4] + f'_{W}.rgba')
print(W, h)

for f in sorted(glob.glob(d + '/m*.png')):
    im = Image.open(f).convert('L'); h = round(im.height * W / im.width)
    (np.asarray(im.resize((W, h), Image.NEAREST)) > 127).astype(np.uint8).tofile(f[:-4] + f'_{W}.m')
