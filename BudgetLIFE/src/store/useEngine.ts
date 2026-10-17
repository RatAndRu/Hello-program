import { useMemo } from 'react';
import { useStore } from './useStore';
import type { EngineCtx } from '../lib/engine';
import { buildEvents, project } from '../lib/engine';
import type { CashflowEvent, ISODate, ProjectionResult } from '../types';
import type { ConvertRates } from '../lib/rates';

/** Контекст движка: данные + курсы + базовая валюта */
export function useCtx(): EngineCtx {
  const data = useStore((s) => s.data);
  return useMemo<EngineCtx>(
    () => ({
      accounts: data.accounts,
      categories: data.categories,
      incomes: data.incomes,
      subscriptions: data.subscriptions,
      credits: data.credits,
      transactions: data.transactions,
      rates: { rates: data.rates?.rates ?? {}, base: data.rates?.base ?? data.settings.baseCurrency, manual: data.settings.manualRates },
      baseCurrency: data.settings.baseCurrency,
    }),
    [data],
  );
}

export function useRates(): ConvertRates {
  const data = useStore((s) => s.data);
  return useMemo(
    () => ({
      rates: data.rates?.rates ?? {},
      base: data.rates?.base ?? data.settings.baseCurrency,
      manual: data.settings.manualRates,
    }),
    [data],
  );
}

export function useEvents(from: ISODate, to: ISODate): CashflowEvent[] {
  const ctx = useCtx();
  return useMemo(() => buildEvents(ctx, from, to), [ctx, from, to]);
}

export function useProjection(from: ISODate, to: ISODate, opts?: { withInterest?: boolean }): ProjectionResult {
  const ctx = useCtx();
  const withInterest = opts?.withInterest ?? true;
  return useMemo(() => project(ctx, from, to, { withInterest }), [ctx, from, to, withInterest]);
}

export function useAccountsMap() {
  const accounts = useStore((s) => s.data.accounts);
  return useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);
}

export function useCategoriesMap() {
  const categories = useStore((s) => s.data.categories);
  return useMemo(() => new Map(categories.map((c) => [c.id, c])), [categories]);
}
