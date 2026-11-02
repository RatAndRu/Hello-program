#!/usr/bin/env python3
"""Сколько обучения влезает в чужие 6 часов: арифметика без магии.

    python docs/train_budget.py                          # таблица сценариев
    python docs/train_budget.py --unet 24 4 96           # посчитать UNet явно
    python docs/train_budget.py --params 5 --res 96 --samples 50000 --epochs 20

Считаем не «по паспорту видеокарты», а по слоям. Для UNet (база C каналов,
L уровней, вход R²) прямой проход — сумма по свёрткам 3×3:

    2 · 9 · C_in · C_out · R²   на каждую свёртку

Обучение — втрое дороже (прямой, обратный, обновление весов). Скорость железа
берём измеренную: numpy im2col-GEMM на 2 ядрах этого сандбокса дал 150 GFLOP/s,
PyTorch на обвязку свёрток съедает ещё примерно столько же, поэтому по
умолчанию КПД 0.5. GitHub-hosted runner — 4 ядра, то есть ×2.

Проверять надо не эту таблицу, а свой шаг обучения: замерить время одного шага
и умножить на число шагов. Скрипт нужен, чтобы понять порядок величины до
того, как писать код.
"""
from __future__ import annotations

import argparse

MEASURED_GFLOPS_2_CORES = 150.0   # numpy im2col 3×3, этот сандбокс, fp32
EFFICIENCY = 0.5                   # доля, которую отдаёт PyTorch на CPU
JOB_HOURS = 6.0                    # потолок одного job на GitHub-hosted runner
GH_CORES = 4                       # столько ядер у публичного раннера


def conv_flops(r: int, cin: int, cout: int, k: int = 3) -> float:
    return 2.0 * k * k * cin * cout * r * r


def conv_params(cin: int, cout: int, k: int = 3) -> float:
    return float(k * k * cin * cout)


def unet(base: int, levels: int, res: int) -> tuple[float, float]:
    """(параметры, FLOPs прямого прохода) для UNet с двойными свёртками."""
    params = flops = 0.0
    chans = [base * 2 ** i for i in range(levels)]
    # энкодер: на каждом уровне две свёртки Cin→Cout→Cout
    for i, c in enumerate(chans):
        r = res // (2 ** i)
        cin = base if i == 0 else chans[i - 1]
        for a, b in ((cin, c), (c, c)):
            params += conv_params(a, b)
            flops += conv_flops(r, a, b)
    # бутылочное горлышко
    r = max(res // (2 ** levels), 1)
    for a, b in ((chans[-1], chans[-1] * 2), (chans[-1] * 2, chans[-1] * 2)):
        params += conv_params(a, b)
        flops += conv_flops(r, a, b)
    # декодер: симметрично, плюс свёртка после склейки
    for i in reversed(range(levels)):
        r = res // (2 ** i)
        c = chans[i]
        cin = chans[-1] * 2 if i == levels - 1 else chans[i + 1]
        for a, b in ((cin + c, c), (c, c)):
            params += conv_params(a, b)
            flops += conv_flops(r, a, b)
    return params, flops


def flops_from_params(params_m: float, res: int) -> float:
    """Калибровка по UNet: ≈0.7 GFLOP на 1 M параметров при входе 96².

    Годится для плотного предсказания (маска, глубина, SDF), а не для
    классификаторов: у ResNet-50 все тяжёлые слои стоят на низком разрешении,
    поэтому «2·N·R²» завышает его в десятки раз (4.1 GFLOP против 2.5 TFLOP).
    """
    return 0.7e9 * params_m * (res / 96.0) ** 2


def to_hours(total_flops: float, gflops: float, eff: float = EFFICIENCY) -> float:
    return total_flops / (gflops * 1e9 * eff) / 3600.0


def fmt_h(h: float) -> str:
    if h < 1:
        return f"{h * 60:.0f} мин"
    if h < 48:
        return f"{h:.1f} ч"
    if h < 24 * 60:
        return f"{h / 24:.1f} сут"
    return f"{h / 24 / 365:.1f} лет"


def main() -> None:
    ap = argparse.ArgumentParser(description="Бюджет обучения в часах")
    ap.add_argument("--params", type=float, help="миллионов параметров (плотная сеть)")
    ap.add_argument("--res", type=int, default=96, help="сторона входа, px")
    ap.add_argument("--samples", type=int, default=30000)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--gflops", type=float, default=MEASURED_GFLOPS_2_CORES)
    ap.add_argument("--efficiency", type=float, default=EFFICIENCY)
    ap.add_argument("--unet", nargs=3, type=int, metavar=("BASE", "LEVELS", "RES"),
                    help="посчитать конкретный UNet: база, уровни, вход")
    args = ap.parse_args()

    cpu2 = args.gflops
    cpu4 = cpu2 * 2
    gpu = 3000.0 * 0.2        # T4-класс: паспорт ~8 TFLOPS fp16, берём 20 %

    if args.unet:
        base, levels, res = args.unet
        p, fwd = unet(base, levels, res)
        total = 3 * fwd * args.samples * args.epochs
        print(f"UNet база {base}, {levels} уровня, вход {res}²")
        print(f"  параметров:    {p / 1e6:.2f} M")
        print(f"  прямой проход: {fwd / 1e9:.2f} GFLOP")
        print(f"  обучение:      {total / 1e15:.2f} PFLOP на {args.samples} × {args.epochs}")
        print(f"  на 2 ядрах: {fmt_h(to_hours(total, cpu2))}"
              f" | 4 ядра: {fmt_h(to_hours(total, cpu4))}"
              f" | GPU: {fmt_h(to_hours(total, gpu, 1.0))}")
        print(f"  job'ов по {JOB_HOURS:.0f} ч на 4 ядрах: {to_hours(total, cpu4) / JOB_HOURS:.1f}")
        return

    if args.params:
        fwd = flops_from_params(args.params, args.res)
        total = 3 * fwd * args.samples * args.epochs
        print(f"модель {args.params:g} M, вход {args.res}², {args.samples} × {args.epochs}")
        print(f"  прямой проход: {fwd / 1e9:.2f} GFLOP/сэмпл")
        print(f"  всё обучение:  {total / 1e15:.2f} PFLOP")
        print(f"  на 2 ядрах: {fmt_h(to_hours(total, cpu2))}"
              f" | 4 ядра: {fmt_h(to_hours(total, cpu4))}"
              f" | GPU: {fmt_h(to_hours(total, gpu, 1.0))}")
        print(f"  job'ов по {JOB_HOURS:.0f} ч на 4 ядрах: {to_hours(total, cpu4) / JOB_HOURS:.1f}")
        return

    rows = [
        # (что это, база каналов, уровней, вход, сэмплов, эпох)
        ("голова: силуэт → 20 чисел формы", 8, 3, 96, 20_000, 30),
        ("UNet 24: силуэт → SDF 32³", 24, 4, 96, 50_000, 20),
        ("UNet 48: маска → глубина 128²", 48, 4, 128, 50_000, 20),
        ("UNet 96: кромки и фаски 192²", 96, 4, 192, 20_000, 10),
    ]
    print(f"КПД {EFFICIENCY:.0%}; замер на 2 ядрах {cpu2:.0f} GFLOP/s; "
          f"4 ядра — {cpu4:.0f}; GPU — {gpu:.0f} полезных\n")
    print("| задача | параметров | вход | сэмплов × эпох | 4 ядра | GPU | в 6-часовой job |")
    print("|---|---:|---|---:|---:|---:|---|")
    for name, base, levels, res, n, ep in rows:
        p, fwd = unet(base, levels, res)
        total = 3 * fwd * n * ep
        h4 = to_hours(total, cpu4)
        hg = to_hours(total, gpu, 1.0)
        jobs = h4 / JOB_HOURS
        fits = ("влезает" if jobs <= 1.2 else
                "почти: 1 job" if jobs <= 1.6 else f"нет, {jobs:.0f} job'ов")
        print(f"| {name} | {p / 1e6:.1f} M | {res}² | {n:,} × {ep} | {fmt_h(h4)} | {fmt_h(hg)} | {fits} |"
              .replace(",", " "))

    print("\nСколько сэмплов пройдёт за один 6-часовой job (4 ядра, КПД 50 %)")
    budget = JOB_HOURS * 3600 * cpu4 * EFFICIENCY * 1e9      # FLOP за один job
    for base, levels, res in [(8, 3, 96), (24, 4, 96), (48, 4, 128)]:
        p, fwd = unet(base, levels, res)
        per = 3 * fwd
        print(f"  UNet {base:>2} ({p / 1e6:.1f} M) при {res}²: "
              f"{budget / per:>10,.0f} сэмплов".replace(",", " "))

    print("\nЧто это значит")
    print("  · специалиста на 1–7 M параметров реально обучить за 1–6 job'ов;")
    print("  · универсальную реконструкцию по фото — нет: там 10³–10⁵ GPU-часов;")
    print("  · поэтому брать готовое (TripoSR, Depth Anything) и учить голову.")
    print("  · данные важнее: 20–50 тыс. пар «фото → форма» — это недели работы,")
    print("    если рисовать руками, и часы, если генерировать своим же ядром.")


if __name__ == "__main__":
    main()
