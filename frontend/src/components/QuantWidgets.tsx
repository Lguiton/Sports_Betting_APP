import React, { useMemo } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

type WidgetData = Record<string, unknown>;

const generatePoissonCurve = (homeLambda: number, awayLambda: number, maxScore = 45) => {
  const factorial = (n: number): number => (n === 0 || n === 1 ? 1 : n * factorial(n - 1));
  const pmf = (k: number, lambda: number) => (Math.pow(lambda, k) * Math.exp(-lambda)) / factorial(k);
  return Array.from({ length: maxScore }, (_, i) => ({
    score: i,
    Home: (pmf(i, homeLambda) * 100).toFixed(2),
    Away: (pmf(i, awayLambda) * 100).toFixed(2),
  }));
};

export const PoissonWidget = ({ data }: { data: WidgetData }) => {
  const chartData = useMemo(() => {
    const hLambda = Number(data.projected_home_lambda) || 24;
    const aLambda = Number(data.projected_away_lambda) || 21;
    return generatePoissonCurve(hLambda, aLambda);
  }, [data]);

  return (
    <div className="flex flex-col gap-2 mt-2">
      <div className="flex items-center justify-between border-b border-[#212533] pb-2 mb-2">
        <span className="text-[#d4af37] font-bold tracking-wider text-[10px] uppercase">Poisson Scoring Distribution</span>
        <span className="bg-[#d4af37]/10 text-[#d4af37] border border-[#d4af37]/20 px-2 py-0.5 rounded text-[9px] font-bold">
          TOTAL: {String(data.projected_total_points ?? "45.0")}
        </span>
      </div>
      <div className="h-48 w-full mt-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="colorHome" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#d4af37" stopOpacity={0.6} />
                <stop offset="95%" stopColor="#d4af37" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="colorAway" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#9ca3af" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#9ca3af" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#181b26" vertical={false} />
            <XAxis dataKey="score" stroke="#4b5563" fontSize={10} tickLine={false} axisLine={false} />
            <YAxis stroke="#4b5563" fontSize={10} tickLine={false} axisLine={false} tickFormatter={(val) => `${val}%`} />
            <Tooltip contentStyle={{ backgroundColor: "#0e1017", borderColor: "#212533", color: "#fff", fontSize: "11px", borderRadius: "8px" }} itemStyle={{ fontSize: "11px", fontWeight: "bold" }} />
            <Area type="monotone" dataKey="Away" stroke="#9ca3af" strokeWidth={2} fillOpacity={1} fill="url(#colorAway)" />
            <Area type="monotone" dataKey="Home" stroke="#d4af37" strokeWidth={2} fillOpacity={1} fill="url(#colorHome)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export const MonteCarloWidget = ({ data }: { data: WidgetData }) => (
  <div className="p-3 border border-[#212533] bg-[#090a0d] rounded-lg mt-2">
    <span className="text-gray-400 font-bold text-[10px] uppercase block mb-1">Monte Carlo Median</span>
    <span className="text-white text-lg font-bold">{String(data.median_projected_score ?? "-")}</span>
  </div>
);

export const ParlayCardWidget = ({ data }: { data: WidgetData }) => (
  <div className="p-4 border border-[#d4af37]/30 bg-[#090a0d] rounded-lg mt-2 flex items-center justify-between">
    <div>
      <span className="text-[#d4af37] font-bold text-[10px] uppercase block mb-1">🎰 $5 Casino Parlay Preview</span>
      <span className="text-white text-xs font-mono">Odds: <strong className="text-[#d4af37]">{String(data.odds ?? "-")}</strong></span>
    </div>
    <div className="text-right">
      <span className="text-gray-500 text-[10px] uppercase block">Potential Return</span>
      <span className="text-green-400 font-bold text-base">${Number(data.potential_payout ?? 0).toFixed(2)}</span>
    </div>
  </div>
);

export const NBAWidget = ({ data }: { data: WidgetData }) => {
  const overProb = Number(data.over_probability) || 50;
  const underProb = 100 - overProb;
  return (
    <div className="flex flex-col gap-3 mt-2 p-4 border border-[#212533] bg-[#090a0d] rounded-lg">
      <div className="flex items-center justify-between border-b border-[#212533] pb-2">
        <span className="text-orange-500 font-bold tracking-wider text-[10px] uppercase">NBA Bivariate Normal</span>
        <span className="bg-orange-500/10 text-orange-500 border border-orange-500/20 px-2 py-0.5 rounded text-[9px] font-bold">
          PROJ TOTAL: {String(data.projected_total ?? "220.5")}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <div className="flex justify-between text-xs font-bold text-gray-300">
          <span>OVER PROBABILITY</span><span className="text-orange-400">{overProb}%</span>
        </div>
        <div className="w-full bg-[#181b26] rounded-full h-2 overflow-hidden">
          <div className="bg-orange-500 h-2 rounded-full" style={{ width: `${overProb}%` }}></div>
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <div className="flex justify-between text-xs font-bold text-gray-300">
          <span>UNDER PROBABILITY</span><span className="text-blue-400">{underProb}%</span>
        </div>
        <div className="w-full bg-[#181b26] rounded-full h-2 overflow-hidden">
          <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${underProb}%` }}></div>
        </div>
      </div>
    </div>
  );
};

export const MLBWidget = ({ data }: { data: WidgetData }) => {
  const homeWin = Number(data.home_win_probability) || 55;
  const awayWin = 100 - homeWin;
  return (
    <div className="flex flex-col gap-3 mt-2 p-4 border border-[#212533] bg-[#090a0d] rounded-lg">
      <div className="flex items-center justify-between border-b border-[#212533] pb-2">
        <span className="text-green-500 font-bold tracking-wider text-[10px] uppercase">MLB Log5 Win Matrix</span>
        <span className="bg-green-500/10 text-green-500 border border-green-500/20 px-2 py-0.5 rounded text-[9px] font-bold">
          {homeWin > awayWin ? "HOME EDGE" : "AWAY EDGE"}
        </span>
      </div>
      <div className="flex items-center justify-between mt-2">
        <div className="flex flex-col items-center">
          <span className="text-[10px] text-gray-500 font-bold uppercase mb-1">Away</span>
          <span className="text-lg font-bold text-gray-300">{awayWin.toFixed(1)}%</span>
        </div>
        <div className="flex-1 px-4 flex items-center justify-center"><span className="text-xs text-gray-600 font-bold">VS</span></div>
        <div className="flex flex-col items-center">
          <span className="text-[10px] text-gray-500 font-bold uppercase mb-1">Home</span>
          <span className="text-lg font-bold text-green-400">{homeWin.toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
};
