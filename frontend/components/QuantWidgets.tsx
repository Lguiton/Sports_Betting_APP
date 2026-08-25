import React from 'react';

// ==========================================
// 🎲 MONTE CARLO WIDGET
// ==========================================
export const MonteCarloWidget = ({ data }) => {
  if (!data) return null;
  
  return (
    <div className="bg-[#0a0a0a] border border-[#d4af37]/30 rounded-md p-4 my-4 font-mono text-sm">
      <div className="flex justify-between items-center border-b border-[#d4af37]/20 pb-2 mb-3">
        <h3 className="text-[#d4af37] font-bold tracking-wider">MONTE CARLO ENGINE (10K RUNS)</h3>
        <span className="text-xs text-[#d4af37]/70 bg-[#d4af37]/10 px-2 py-1 rounded">ACTIVE</span>
      </div>
      
      <div className="grid grid-cols-2 gap-4 text-gray-300">
        <div className="flex flex-col">
          <span className="text-xs text-gray-500 uppercase">Matchup</span>
          <span className="font-semibold">{data.matchup}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs text-gray-500 uppercase">Median Projected Score</span>
          <span className="font-semibold text-white">{data.median_projected_score}</span>
        </div>
        
        <div className="flex flex-col bg-[#111] p-2 rounded border border-[#d4af37]/10">
          <span className="text-xs text-[#d4af37]/70 uppercase">Home Win Prob</span>
          <span className="text-lg text-[#d4af37]">{data.home_win_probability}</span>
        </div>
        <div className="flex flex-col bg-[#111] p-2 rounded border border-[#d4af37]/10">
          <span className="text-xs text-[#d4af37]/70 uppercase">Away Win Prob</span>
          <span className="text-lg text-[#d4af37]">{data.away_win_probability}</span>
        </div>
      </div>
    </div>
  );
};

// ==========================================
// 📐 POISSON OVER/UNDER WIDGET
// ==========================================
export const PoissonWidget = ({ data }) => {
  if (!data) return null;

  const isOverValue = data.edge_recommendation === "OVER VALUE";
  const isUnderValue = data.edge_recommendation === "UNDER VALUE";

  return (
    <div className="bg-[#0a0a0a] border border-[#d4af37]/30 rounded-md p-4 my-4 font-mono text-sm">
      <div className="flex justify-between items-center border-b border-[#d4af37]/20 pb-2 mb-3">
        <h3 className="text-[#d4af37] font-bold tracking-wider">POISSON GLM DISTRIBUTION</h3>
        <span className="text-xs text-[#d4af37]/70 bg-[#d4af37]/10 px-2 py-1 rounded">O/U PROJECTION</span>
      </div>
      
      <div className="flex justify-between items-center mb-4 text-gray-300">
        <div className="flex flex-col text-center">
          <span className="text-xs text-gray-500">Home $\lambda$</span>
          <span className="text-lg">{data.projected_home_lambda}</span>
        </div>
        <div className="flex flex-col text-center">
          <span className="text-xs text-[#d4af37]">Proj Total</span>
          <span className="text-xl font-bold text-white">{data.projected_total_points}</span>
        </div>
        <div className="flex flex-col text-center">
          <span className="text-xs text-gray-500">Away $\lambda$</span>
          <span className="text-lg">{data.projected_away_lambda}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className={`p-2 rounded flex justify-between ${isOverValue ? 'bg-[#d4af37]/20 border border-[#d4af37]' : 'bg-[#111] border border-transparent'}`}>
          <span className="text-gray-400">OVER {data.vegas_line}</span>
          <span className={isOverValue ? 'text-[#d4af37] font-bold' : 'text-gray-300'}>{data.over_probability_pct}%</span>
        </div>
        <div className={`p-2 rounded flex justify-between ${isUnderValue ? 'bg-[#d4af37]/20 border border-[#d4af37]' : 'bg-[#111] border border-transparent'}`}>
          <span className="text-gray-400">UNDER {data.vegas_line}</span>
          <span className={isUnderValue ? 'text-[#d4af37] font-bold' : 'text-gray-300'}>{data.under_probability_pct}%</span>
        </div>
      </div>

      <div className="w-full text-center p-2 bg-black border border-[#d4af37]/40 text-[#d4af37] font-bold tracking-widest rounded">
        {data.edge_recommendation}
      </div>
    </div>
  );
};
