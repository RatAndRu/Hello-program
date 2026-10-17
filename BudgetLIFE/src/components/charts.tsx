import { useId, type ReactNode } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import clsx from 'clsx';
import type { DayPoint } from '../types';
import { Icon } from './Icon';
import { fmtMoney, fmtNumber } from '../lib/format';
import { fmtDateShort, fromISO } from '../lib/dates';
import { Card } from './ui/primitives';

/* ============================ обёртка графика ============================== */

export function ChartCard({
  title,
  subtitle,
  right,
  children,
  className,
  bodyClassName,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  icon?: string;
}) {
  return (
    <Card className={clsx('flex flex-col', className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          {icon && (
            <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-brand-300">
              <Icon name={icon} size={14} />
            </span>
          )}
          <div>
            <h3 className="text-[14px] font-semibold text-slate-100">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
        </div>
        {right}
      </div>
      <div className={clsx('min-w-0 flex-1', bodyClassName)}>{children}</div>
    </Card>
  );
}

/* ================================ тултипы ================================== */

interface TooltipEntry {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

function TooltipShell({ title, children }: { title?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-ink-900/95 px-3 py-2 text-xs shadow-2xl backdrop-blur-xl">
      {title && <div className="mb-1 font-semibold text-slate-200">{title}</div>}
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({ color, label, value }: { color?: string; label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="flex items-center gap-1.5 text-slate-400">
        {color && <span className="h-2 w-2 rounded-full" style={{ background: color }} />}
        {label}
      </span>
      <span className="num font-medium text-slate-100">{value}</span>
    </div>
  );
}

export function makeMoneyTooltip(currency: string, hide?: boolean) {
  return function MoneyTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipEntry[]; label?: string | number }) {
    if (!active || !payload?.length) return null;
    const title =
      typeof label === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(label) ? fmtDateShort(label) : String(label ?? '');
    return (
      <TooltipShell title={title}>
        {payload.map((p, i) => (
          <Row
            key={i}
            color={p.color}
            label={p.name}
            value={typeof p.value === 'number' ? fmtMoney(p.value, currency, { hide }) : String(p.value ?? '')}
          />
        ))}
      </TooltipShell>
    );
  };
}

/* ============================ график баланса =============================== */

export function BalanceChart({
  days,
  currency,
  hide,
  height = 260,
  showMinLine = true,
}: {
  days: DayPoint[];
  currency: string;
  hide?: boolean;
  height?: number;
  showMinLine?: boolean;
}) {
  const gid = useId().replace(/:/g, '');
  const data = days.map((d) => ({
    date: d.date,
    balance: Math.round(d.balance * 100) / 100,
    income: Math.round(d.income * 100) / 100,
    expense: Math.round(d.expense * 100) / 100,
  }));
  const min = data.length ? Math.min(...data.map((d) => d.balance)) : 0;
  const max = data.length ? Math.max(...data.map((d) => d.balance)) : 0;
  const pad = Math.max(1, (max - min) * 0.15);

  if (!data.length) {
    return <div className="grid h-[260px] place-items-center text-sm text-slate-500">Нет данных за период</div>;
  }

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`fill-${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#38c3f5" stopOpacity={0.45} />
              <stop offset="55%" stopColor="#38c3f5" stopOpacity={0.12} />
              <stop offset="100%" stopColor="#38c3f5" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={(v: string) => fmtDateShort(v)}
            tick={{ fill: '#64748b', fontSize: 11 }}
            axisLine={{ stroke: 'rgba(255,255,255,0.08)' }}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            tickFormatter={(v: number) => fmtMoney(v, currency, { hide, cents: false, compact: true, tight: true })}
            tick={{ fill: '#64748b', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={78}
            domain={[Math.floor(min - pad), Math.ceil(max + pad)]}
          />
          <Tooltip content={makeMoneyTooltip(currency, hide)} />
          {showMinLine && min < 0 && <ReferenceLine y={0} stroke="rgba(244,63,94,0.5)" strokeDasharray="4 4" />}
          <Area
            type="monotone"
            dataKey="balance"
            name="Баланс"
            stroke="#38c3f5"
            strokeWidth={2.2}
            fill={`url(#fill-${gid})`}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0, fill: '#38c3f5' }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ========================== доходы / расходы =============================== */

export interface MonthBar {
  label: string;
  income: number;
  expense: number;
  net?: number;
  incomeDone?: number;
  expenseDone?: number;
}

export function CashflowBars({
  data,
  currency,
  hide,
  height = 280,
  stacked = false,
}: {
  data: MonthBar[];
  currency: string;
  hide?: boolean;
  height?: number;
  stacked?: boolean;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={4}>
          <defs>
            <linearGradient id="bar-in" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#34e5b0" stopOpacity={0.95} />
              <stop offset="100%" stopColor="#10d19a" stopOpacity={0.55} />
            </linearGradient>
            <linearGradient id="bar-out" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fb7d8e" stopOpacity={0.95} />
              <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.5} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={{ stroke: 'rgba(255,255,255,0.08)' }} tickLine={false} />
          <YAxis
            tickFormatter={(v: number) => fmtMoney(v, currency, { hide, cents: false, compact: true, tight: true })}
            tick={{ fill: '#64748b', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={78}
          />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            content={makeMoneyTooltip(currency, hide)}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, color: '#94a3b8' }}
            iconType="circle"
            iconSize={8}
          />
          <Bar dataKey="income" name="Доходы" fill="url(#bar-in)" radius={[6, 6, 0, 0]} stackId={stacked ? 'a' : undefined} maxBarSize={38} />
          <Bar dataKey="expense" name="Расходы" fill="url(#bar-out)" radius={[6, 6, 0, 0]} stackId={stacked ? 'a' : undefined} maxBarSize={38} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* =============================== «пончик» ================================== */

export interface Slice {
  name: string;
  value: number;
  color: string;
}

export function CategoryDonut({
  data,
  currency,
  hide,
  height = 260,
  centerLabel,
}: {
  data: Slice[];
  currency: string;
  hide?: boolean;
  height?: number;
  centerLabel?: ReactNode;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="relative w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius="58%"
            outerRadius="86%"
            paddingAngle={2}
            stroke="rgba(7,11,22,0.9)"
            strokeWidth={2}
          >
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
          </Pie>
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0] as unknown as TooltipEntry;
              const v = Number(p.value ?? 0);
              const share = total > 0 ? (v / total) * 100 : 0;
              return (
                <TooltipShell>
                  <Row color={p.color} label={p.name} value={fmtMoney(v, currency, { hide })} />
                  <Row label="Доля" value={`${share.toFixed(1)} %`} />
                </TooltipShell>
              );
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        {centerLabel ?? (
          <>
            <div className="text-[11px] uppercase tracking-wider text-slate-500">Всего</div>
            <div className="num text-lg font-semibold text-slate-100">{fmtMoney(total, currency, { hide, compact: true })}</div>
          </>
        )}
      </div>
    </div>
  );
}

/* ================================ спарклайн ================================ */

export function Sparkline({
  values,
  color = '#38c3f5',
  height = 40,
}: {
  values: number[];
  color?: string;
  height?: number;
}) {
  const data = values.map((v, i) => ({ i, v }));
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 2 }}>
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ============================ линейный график ============================== */

export function LineSeries({
  data,
  keys,
  currency,
  hide,
  height = 260,
}: {
  data: Record<string, string | number>[];
  keys: { key: string; name: string; color: string }[];
  currency: string;
  hide?: boolean;
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={{ stroke: 'rgba(255,255,255,0.08)' }} tickLine={false} />
          <YAxis
            tickFormatter={(v: number) => fmtMoney(v, currency, { hide, cents: false, compact: true, tight: true })}
            tick={{ fill: '#64748b', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={78}
          />
          <Tooltip content={makeMoneyTooltip(currency, hide)} />
          <Legend wrapperStyle={{ fontSize: 12, color: '#94a3b8' }} iconType="circle" iconSize={8} />
          {keys.map((k) => (
            <Line key={k.key} type="monotone" dataKey={k.key} name={k.name} stroke={k.color} strokeWidth={2.2} dot={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Форматтер подписей для компактных сумм на осях */
export const axisMoney = (v: number, currency: string, hide?: boolean) =>
  fmtMoney(v, currency, { hide, cents: false, compact: true, tight: true });

export const dayTick = (iso: string) => `${fromISO(iso).getDate()}`;

export const numTick = (v: number) => fmtNumber(v, 0);
