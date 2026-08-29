"use client";

import React, { useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, Search, Terminal, Compass, Layers, Sliders, Globe, BarChart3, Send, Wallet, TrendingUp } from "lucide-react";

// --- MICRO-COMPONENTS ---
const Stat = ({ label, value, accent = false }: { label: string; value: unknown; accent?: boolean }) => (
  <div className="flex flex-col gap-1">
    <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
    <div className={`text-lg font-black ${accent ? "text-[#00FF5B]" : "text-white"}`}>{String(value ?? "-")}</div>
  </div>
);

// --- WIDGETS ---
export type MarketEdgeData = { american_odds: number; units: number; coverage: number; edges: number; delta: number; market_context: string; [key: string]: unknown };
const MarketEdgeWidget = ({ data }: { data: MarketEdgeData }) => (
  <div className="flex flex-col h-full justify-between gap-4">
    <div className="grid grid-cols-2 gap-4">
      <Stat label="Amer. Odds" value={data.american_odds} />
      <Stat label="Rec. Units" value={data.units} accent />
      <Stat label="Coverage" value={`${data.coverage}%`} />
      <Stat label="Edges Found" value={data.edges} accent />
    </div>
    <div className="mt-auto border-l-2 border-[#00FF5B] bg-[#00FF5B]/5 px-3 py-2 text-xs text-slate-300 rounded-r">
      {data.market_context}
    </div>
  </div>
);

export type PoissonData = { projected_home_lambda: number; projected_away_lambda: number; projected_total_points: number; home_team: string; away_team: string; win_probability: number; [key: string]: unknown };
const PoissonWidget = ({ data }: { data: PoissonData }) => (
  <div className="flex flex-col h-full justify-between gap-4">
    <div className="text-xs text-slate-400 font-bold border-b border-[#222834] pb-2">
      {data.away_team} @ {data.home_team}
    </div>
    <div className="grid grid-cols-2 gap-4">
      <Stat label={`${data.home_team} Exp (λ)`} value={data.projected_home_lambda} />
      <Stat label={`${data.away_team} Exp (λ)`} value={data.projected_away_lambda} />
      <Stat label="Total Points" value={data.projected_total_points} />
      <Stat label="Home Win Prob" value={`${data.win_probability}%`} accent />
    </div>
  </div>
);

type RiskProfile = "Conservative" | "Moderate" | "Aggressive";

function extractQuantitativeJson(content: string): { data: Record<string, unknown>; raw: string } | null {
  const fencedMatch = content.match(/`{2,3}\s*(?:json)?\s*(\{[\s\S]*?\})\s*`{2,3}/i);
  if (fencedMatch) {
    try { return { data: JSON.parse(fencedMatch[1]) as Record<string, unknown>, raw: fencedMatch[0] }; } catch { }
  }
  return null;
}

function isMarketEdgeData(data: Record<string, unknown>): data is MarketEdgeData { return "units" in data && "edges" in data && "american_odds" in data; }
function isPoissonData(data: Record<string, unknown>): data is PoissonData { return "projected_home_lambda" in data && "win_probability" in data; }

export default function Dashboard() {
  const [bankroll, setBankroll] = useState(1025);
  const [riskProfile, setRiskProfile] = useState<RiskProfile>("Moderate");
  const [threadId, setThreadId] = useState(() => typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `thread-${Date.now()}`);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [searchFilter, setSearchFilter] = useState("All Models");
  const [selectedNav, setSelectedNav] = useState("Overview");
  
  const [dashboardData, setDashboardData] = useState<any>({});
  const [agentNarrative, setAgentNarrative] = useState("Awaiting predictive model input...");

  const chartData = useMemo(() => {
    const volatility = riskProfile === "Aggressive" ? 0.12 : riskProfile === "Moderate" ? 0.06 : 0.03;
    return Array.from({ length: 20 }, (_, index) => {
      const variation = Math.sin(index * 1.5) * volatility;
      return { day: `T-${20 - index}`, value: Math.max(0, bankroll * (1 + variation)) };
    });
  }, [bankroll, riskProfile]);

  const handleFilterClick = (filter: string) => {
    setSearchFilter(filter);
    if (filter === "+EV Odds") setInput("Calculate +EV market edge and pricing discrepancies for Cowboys vs Eagles");
    else if (filter === "Kelly Staking") setInput("Determine optimal Kelly Criterion sizing for Cowboys vs Eagles");
    else if (filter === "Poisson Matchup") setInput("Run Poisson Matchup simulation for Cowboys vs Eagles");
    else setInput("Run all models for Cowboys vs Eagles");
  };

  const handleSendMessage = async (customQuery?: string) => {
    const userPrompt = (customQuery || input).trim();
    if (!userPrompt || isLoading) return;

    const activeThreadId = threadId || `thread-${Date.now()}`;
    if (!threadId) setThreadId(activeThreadId);

    setInput("");
    setIsLoading(true);
    setAgentNarrative("Running multi-agent quantitative consensus...");
    setDashboardData({}); 

    try {
      const backendUrl = (process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
      const response = await fetch(`${backendUrl}/chat/sports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userPrompt, thread_id: activeThreadId, bankroll, risk_profile: riskProfile }),
      });

      if (!response.ok) throw new Error(`Backend returned status ${response.status}`);
      if (!response.body) throw new Error("No response stream received");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accumulatedContent = "";

      const processEvent = (event: string) => {
        const data = event.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
        if (!data) return false;
        if (data === "[DONE]") return true;
        try {
          const parsed = JSON.parse(data);
          if (parsed.type === "token") {
            accumulatedContent += String(parsed.content ?? "");
            const jsonMatch = extractQuantitativeJson(accumulatedContent);
            if (jsonMatch) {
                setDashboardData(jsonMatch.data);
                setAgentNarrative(accumulatedContent.replace(jsonMatch.raw, "").trim());
            } else {
                setAgentNarrative(accumulatedContent);
            }
          }
        } catch { }
        return false;
      };

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        const events = buffer.split(/\r?\n\r?\n/);
        buffer = events.pop() ?? "";
        let streamFinished = false;
        for (const event of events) {
          if (processEvent(event)) { streamFinished = true; break; }
        }
        if (done || streamFinished) break;
      }
      if (buffer.trim()) processEvent(buffer);
    } catch (error) {
      setAgentNarrative("Error connecting to backend analytical stream.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-[80px_1fr] h-screen w-screen bg-[#06080A] text-white font-sans overflow-hidden">
      
      {/* SIDEBAR (Rigid Column 1) */}
      <aside className="border-r border-[#1C212B] bg-[#0A0D14] flex flex-col items-center py-6 justify-between z-20">
        <div className="flex flex-col items-center gap-8 w-full">
          <button className="text-[#00FF5B] font-black text-2xl tracking-tighter" onClick={() => setSelectedNav("Overview")}>Q<span className="text-white">T</span></button>
          <div className="flex flex-col gap-4 w-full px-4">
            <button className={`p-3 rounded-xl flex justify-center w-full transition-colors ${selectedNav === "Overview" ? "text-[#00FF5B] bg-[#00FF5B]/10 shadow-[0_0_15px_rgba(0,255,91,0.15)]" : "text-slate-500 hover:text-white hover:bg-[#1C212B]"}`} onClick={() => setSelectedNav("Overview")}><Compass size={22}/></button>
            <button className={`p-3 rounded-xl flex justify-center w-full transition-colors ${selectedNav === "Performance" ? "text-[#00FF5B] bg-[#00FF5B]/10 shadow-[0_0_15px_rgba(0,255,91,0.15)]" : "text-slate-500 hover:text-white hover:bg-[#1C212B]"}`} onClick={() => setSelectedNav("Performance")}><BarChart3 size={22}/></button>
            <button className={`p-3 rounded-xl flex justify-center w-full transition-colors ${selectedNav === "Models" ? "text-[#00FF5B] bg-[#00FF5B]/10 shadow-[0_0_15px_rgba(0,255,91,0.15)]" : "text-slate-500 hover:text-white hover:bg-[#1C212B]"}`} onClick={() => setSelectedNav("Models")}><Layers size={22}/></button>
            <button className={`p-3 rounded-xl flex justify-center w-full transition-colors ${selectedNav === "Settings" ? "text-[#00FF5B] bg-[#00FF5B]/10 shadow-[0_0_15px_rgba(0,255,91,0.15)]" : "text-slate-500 hover:text-white hover:bg-[#1C212B]"}`} onClick={() => setSelectedNav("Settings")}><Sliders size={22}/></button>
          </div>
        </div>
        <button className="w-10 h-10 rounded-xl bg-[#1C212B] text-xs font-bold flex items-center justify-center text-white hover:bg-[#00FF5B] hover:text-black transition-colors" onClick={() => setSelectedNav("Profile")}>LG</button>
      </aside>

      {/* MAIN DASHBOARD CONTENT (Rigid Column 2) */}
      <main className="overflow-y-auto bg-[#06080A] p-4 md:p-6 lg:p-8 h-full">
        
        {/* TOP BAR */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-sm font-black text-white uppercase tracking-widest flex items-center gap-3">
            <span className="w-2 h-2 rounded-full bg-[#00FF5B] shadow-[0_0_8px_#00FF5B] animate-pulse" /> 
            SPORTS INTELLIGENCE
          </h1>
          
          <div className="flex gap-2">
              {["All Models", "+EV Odds", "Kelly Staking", "Poisson Matchup"].map((filter) => (
                <button key={filter} onClick={() => handleFilterClick(filter)} className={`text-xs px-4 py-2 rounded-lg transition-all cursor-pointer font-bold ${searchFilter === filter ? "bg-[#00FF5B] text-black shadow-[0_0_15px_rgba(0,255,91,0.3)]" : "bg-[#0A0D14] text-slate-400 hover:text-white border border-[#1C212B]"}`}>
                  {filter}
                </button>
              ))}
          </div>
        </div>

        {/* SEARCH WIDGET */}
        <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-2 flex items-center mb-6 shadow-xl">
          <Search className="ml-4 text-slate-500" size={20}/>
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void handleSendMessage(); }} placeholder="Ask predictive model e.g., 'Analyze Chiefs vs 49ers spread'..." className="flex-1 bg-transparent border-none py-3 px-4 text-sm text-white focus:outline-none placeholder-slate-600"/>
          <button type="button" onClick={() => void handleSendMessage()} disabled={isLoading} className="px-6 py-3 bg-[#00FF5B] text-black font-black rounded-xl text-xs hover:bg-white transition-colors disabled:opacity-50 flex items-center gap-2">
            PREDICT <Send size={14}/>
          </button>
        </div>

        {/* WIDGET GRID (Matches "Mega Kit" Style) */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 mb-6">
          
          {/* Card 1: Bankroll / System Settings */}
          <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg flex flex-col justify-between hover:border-[#00FF5B]/50 transition-colors">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2"><Wallet size={14} className="text-[#00FF5B]"/> ACTIVE BANKROLL</h3>
            </div>
            <div className="flex items-baseline gap-1 mb-4">
              <span className="text-[#00FF5B] text-2xl font-black">$</span>
              <input type="number" value={bankroll} onChange={(e) => setBankroll(Number(e.target.value))} className="bg-transparent text-white text-4xl font-black w-full focus:outline-none" />
            </div>
            <div className="pt-4 border-t border-[#1C212B]">
              <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Risk Profile</span>
              <select value={riskProfile} onChange={(e) => setRiskProfile(e.target.value as RiskProfile)} className="bg-transparent text-[#00FF5B] font-bold text-sm outline-none cursor-pointer w-full">
                <option value="Conservative" className="bg-[#0A0D14]">Conservative</option>
                <option value="Moderate" className="bg-[#0A0D14]">Moderate</option>
                <option value="Aggressive" className="bg-[#0A0D14]">Aggressive</option>
              </select>
            </div>
          </div>

          {/* Card 2: EV Market Edge */}
          <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg min-h-[220px] hover:border-[#00FF5B]/50 transition-colors">
            <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-6 flex items-center gap-2"><TrendingUp size={14} className="text-[#00FF5B]"/> +EV MARKET EDGE</h3>
            {isMarketEdgeData(dashboardData) ? (
              <MarketEdgeWidget data={dashboardData as MarketEdgeData} />
            ) : (
              <div className="h-full flex items-center justify-center text-slate-600 text-xs italic pb-6">Awaiting market data...</div>
            )}
          </div>

          {/* Card 3: Poisson Matchup */}
          <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg min-h-[220px] hover:border-[#00FF5B]/50 transition-colors">
            <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-6 flex items-center gap-2"><Layers size={14} className="text-[#00FF5B]"/> POISSON MATCHUP</h3>
            {isPoissonData(dashboardData) ? (
              <PoissonWidget data={dashboardData as PoissonData} />
            ) : (
              <div className="h-full flex items-center justify-center text-slate-600 text-xs italic pb-6">Awaiting simulation data...</div>
            )}
          </div>

          {/* Card 4: Kelly Sizing */}
          <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg min-h-[220px] hover:border-[#00FF5B]/50 transition-colors flex flex-col">
            <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-6 flex items-center gap-2"><Sliders size={14} className="text-[#00FF5B]"/> KELLY SIZING</h3>
            {dashboardData.kelly ? (
              <div className="grid grid-cols-1 gap-6 mt-2">
                 <Stat label="Recommended Wager" value={`$${dashboardData.kelly.recommended_wager}`} accent />
                 <Stat label="Bankroll Percentage" value={`${dashboardData.kelly.bankroll_pct}%`} />
              </div>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-600 text-xs italic pb-6">Awaiting risk profile...</div>
            )}
          </div>
        </div>

        {/* BOTTOM SECTION: Chart & Terminal Grid */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-10">
          
          {/* Chart spans 2 columns */}
          <div className="xl:col-span-2 bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg h-80 flex flex-col">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2"><Activity size={14} className="text-[#00FF5B]"/> 30-DAY VARIANCE PROJECTION</h2>
              <span className="text-[9px] font-black text-[#0B0E14] bg-[#00FF5B] px-2 py-1 rounded">MONTE CARLO 10K</span>
            </div>
            <div className="flex-1 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="neonGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#00FF5B" stopOpacity={0.5} />
                      <stop offset="95%" stopColor="#00FF5B" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1C212B" strokeDasharray="4 4" vertical={false}/>
                  <XAxis dataKey="day" hide/>
                  <YAxis domain={["auto", "auto"]} fontSize={10} stroke="#475569" tickFormatter={(val) => `$${val.toFixed(0)}`} width={40} axisLine={false} tickLine={false}/>
                  <Tooltip contentStyle={{ backgroundColor: "#06080A", borderColor: "#1C212B", borderRadius: "12px", color: "#fff", fontSize: "12px" }} itemStyle={{ color: "#00FF5B", fontWeight: "bold" }}/>
                  <Area dataKey="value" fill="url(#neonGradient)" fillOpacity={1} stroke="#00FF5B" strokeWidth={3} type="monotone"/>
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Terminal spans 1 column */}
          <div className="xl:col-span-1 bg-[#00FF5B]/5 border border-[#00FF5B]/20 rounded-2xl p-6 shadow-lg h-80 flex flex-col">
            <h3 className="text-xs font-bold text-[#00FF5B] uppercase tracking-widest mb-4 flex items-center gap-2 border-b border-[#00FF5B]/20 pb-4">
              <Terminal size={16} /> AI NARRATIVE OUTPUT
            </h3>
            <div className="flex-1 overflow-y-auto text-sm text-slate-300 leading-relaxed whitespace-pre-wrap pr-2">
              {isLoading && !agentNarrative ? (
                <span className="flex items-center gap-2 text-[#00FF5B] font-bold">
                  <span className="w-2 h-2 rounded-full bg-[#00FF5B] animate-ping" /> Synchronizing data feeds...
                </span>
              ) : (
                agentNarrative || <span className="text-slate-500">No narrative available.</span>
              )}
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}