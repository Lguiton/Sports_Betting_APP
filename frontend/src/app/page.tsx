"use client";

import { useState, useEffect, useCallback } from "react";
import { TrendingUp, Layers, Sliders, Activity, Terminal, Send, Search } from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { motion, AnimatePresence } from "framer-motion";

import MarketEdgeWidget from "@/components/MarketEdgeWidget";
import PoissonWidget from "@/components/PoissonWidget";
import Stat from "@/components/Stat";
import OddsCompare from "@/components/OddsCompare";
import ArbitrageScanner from "@/components/ArbitrageScanner";
import BetJournal from "@/components/BetJournal";
import RatingsPanel from "@/components/RatingsPanel";
import EdgeRadar from "@/components/EdgeRadar";
import Calibration from "@/components/Calibration";
import LineMovement from "@/components/LineMovement";
import Schedule from "@/components/Schedule";
import StatsPanel from "@/components/StatsPanel";
import { useDashboardStore } from "@/store/useDashboardStore";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export default function Page() {
  const {
    riskProfile,
    activeTab,
    setActiveTab,
    dashboardData,
    setDashboardData,
    agentNarrative,
    appendNarrative,
    clearNarrative,
    isLoading,
    setIsLoading,
  } = useDashboardStore();

  // Real cumulative P/L from bets you've actually logged and graded in the
  // Journal tab -- not a simulated random walk. Empty until you grade a bet.
  const [chartData, setChartData] = useState<{ day: number; value: number }[]>([]);
  const [promptInput, setPromptInput] = useState("");

  const isMarketEdgeData = (data: any) =>
    data?.edge_pct || data?.expected_value || data?.best_book || data?.arbitrage;

  const isPoissonData = (data: any) =>
    data?.projected_total_points || data?.over_probability_pct || data?.poisson || data?.projected_home_lambda;

  const refreshBankrollCurve = useCallback(async () => {
    try {
      const res = await fetch(`${backendUrl()}/performance`);
      if (!res.ok) return;
      const perf = await res.json();
      const curve = (perf.bankroll_curve || []).map((point: { cumulative_profit: number }, i: number) => ({
        day: i + 1,
        value: point.cumulative_profit,
      }));
      setChartData(curve);
    } catch (err) {
      console.error("Failed to load bankroll curve:", err);
    }
  }, []);

  useEffect(() => {
    refreshBankrollCurve();
  }, [refreshBankrollCurve, activeTab]);

  async function handleSearchQuery(e: React.FormEvent) {
    e.preventDefault();
    if (!promptInput.trim()) return;

    setIsLoading(true);
    clearNarrative();

    try {
      const response = await fetch(`${backendUrl()}/chat/sports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: promptInput,
          risk_profile: riskProfile,
          bankroll: 1000,
        }),
      });

      if (!response.body) throw new Error("No response body available for stream.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: [JSON_PAYLOAD]")) {
            const jsonText = line.replace("data: [JSON_PAYLOAD]", "");
            try {
              const parsed = JSON.parse(jsonText);
              setDashboardData(parsed);
              
            } catch (err) {
              console.error("Dashboard JSON Parsing Error:", err);
            }
          } else if (line.startsWith("data: ")) {
            const textContent = line.replace("data: ", "");
            appendNarrative(textContent + " ");
          }
        }
      }
    } catch (err) {
      console.error("Stream connection error:", err);
      appendNarrative("\n[ERROR]: Failed to connect to FastAPI backend server.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="p-6 text-white bg-[#06080A] min-h-screen">
      
      {/* TOP NAVIGATION & SEARCH BAR */}
      <motion.nav 
        initial={{ opacity: 0, y: -10 }} 
        animate={{ opacity: 1, y: 0 }} 
        className="flex flex-col md:flex-row justify-between items-center bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-4 mb-6 shadow-xl gap-4"
      >
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full bg-[#00FF5B] animate-pulse" />
          <h1 className="text-sm font-black tracking-wider uppercase text-white">
            Eivanta <span className="text-[#00FF5B]">Analytics</span> Terminal
          </h1>
        </div>

        <form onSubmit={handleSearchQuery} className="flex-1 max-w-md w-full relative flex items-center">
          <Search className="absolute left-3 text-slate-500" size={16} />
          <input
            type="text"
            value={promptInput}
            onChange={(e) => setPromptInput(e.target.value)}
            placeholder="Ask agent (e.g., Analyze underdog value)..."
            className="w-full bg-[#06080A] border border-[#1C212B] rounded-xl pl-10 pr-10 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-[#00FF5B] transition-colors"
          />
          <button type="submit" className="absolute right-3 text-[#00FF5B] hover:text-white transition-colors">
            <Send size={14} />
          </button>
        </form>

        <div className="flex items-center gap-1 bg-[#06080A] p-1 rounded-xl border border-[#1C212B]">
          {(["dashboard", "odds", "arbitrage", "simulation", "journal", "ratings", "radar", "calibration", "lines", "schedule", "stats"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                activeTab === tab 
                  ? "bg-[#00FF5B] text-[#06080A] shadow-md shadow-[#00FF5B]/20" 
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </motion.nav>

      {/* TAB 1: MAIN QUANT DASHBOARD VIEW */}
      <AnimatePresence mode="wait">
        {activeTab === "dashboard" && (
          <motion.div
            key="dashboard"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
          >
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-8">

              <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg min-h-[220px] hover:border-[#00FF5B]/50 transition-colors">
                <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-6 flex items-center gap-2">
                  <TrendingUp className="text-[#00FF5B]" size={14} /> +EV MARKET EDGE
                </h3>
                {isMarketEdgeData(dashboardData) ? (
                  <MarketEdgeWidget data={dashboardData} />
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-600 text-xs italic pb-6">
                    Awaiting market data...
                  </div>
                )}
              </div>

              <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg min-h-[220px] hover:border-[#00FF5B]/50 transition-colors">
                <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-6 flex items-center gap-2">
                  <Layers className="text-[#00FF5B]" size={14} /> POISSON MATCHUP
                </h3>
                {isPoissonData(dashboardData) ? (
                  <PoissonWidget data={dashboardData} />
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-600 text-xs italic pb-6">
                    Awaiting simulation data...
                  </div>
                )}
              </div>

              <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg min-h-[220px] hover:border-[#00FF5B]/50 transition-colors flex flex-col">
                <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-6 flex items-center gap-2">
                  <Sliders className="text-[#00FF5B]" size={14} /> KELLY SIZING
                </h3>
                {dashboardData.kelly || dashboardData.recommended_wager || dashboardData.wager ? (
                  <div className="grid grid-cols-1 gap-4 mt-2">
                    <Stat
                      label="Recommended Wager"
                      value={`$${dashboardData.kelly?.recommended_wager ?? dashboardData.recommended_wager ?? dashboardData.wager ?? 0}`}
                      accent
                    />
                    <Stat
                      label="Bankroll Percentage"
                      value={`${dashboardData.kelly?.bankroll_pct ?? dashboardData.bankroll_percentage ?? dashboardData.bankroll_pct ?? dashboardData.percentage ?? 0}%`}
                    />
                  </div>
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-600 text-xs italic pb-6">
                    Awaiting risk profile...
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-10">
              <div className="xl:col-span-2 bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg h-80 flex flex-col">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                    <Activity className="text-[#00FF5B]" size={14} /> BANKROLL CURVE (LOGGED BETS)
                  </h2>
                  <span className="text-[9px] font-black text-[#0B0E14] bg-[#00FF5B] px-2 py-1 rounded">
                    REAL P/L
                  </span>
                </div>
                <div className="flex-1 w-full">
                  {chartData.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-slate-600 text-xs italic text-center px-6">
                      No graded bets yet -- log and grade a bet in the Journal tab to start building your real bankroll curve.
                    </div>
                  ) : (
                    <ResponsiveContainer height="100%" width="100%">
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient id="neonGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#00FF5B" stopOpacity={0.5} />
                            <stop offset="95%" stopColor="#00FF5B" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid stroke="#1C212B" strokeDasharray="4 4" vertical={false} />
                        <XAxis dataKey="day" hide />
                        <YAxis
                          domain={["auto", "auto"]}
                          fontSize={10}
                          stroke="#475569"
                          tickFormatter={(val) => `$${val.toFixed(0)}`}
                          width={40}
                          axisLine={false}
                          tickLine={false}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "#06080A",
                            borderColor: "#1C212B",
                            borderRadius: "12px",
                            color: "#fff",
                            fontSize: "12px",
                          }}
                          itemStyle={{ color: "#00FF5B", fontWeight: "bold" }}
                        />
                        <Area
                          dataKey="value"
                          fill="url(#neonGradient)"
                          fillOpacity={1}
                          stroke="#00FF5B"
                          strokeWidth={3}
                          type="monotone"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              <div className="xl:col-span-1 bg-[#00FF5B]/5 border border-[#00FF5B]/20 rounded-2xl p-6 shadow-lg h-80 flex flex-col">
                <h3 className="text-xs font-bold text-[#00FF5B] uppercase tracking-widest mb-4 flex items-center gap-2 border-b border-[#00FF5B]/20 pb-4">
                  <Terminal size={16} /> AI NARRATIVE OUTPUT
                </h3>
                <div className="flex-1 overflow-y-auto text-sm text-slate-300 leading-relaxed whitespace-pre-wrap pr-2">
                  {isLoading && !agentNarrative ? (
                    <span className="flex items-center gap-2 text-[#00FF5B] font-bold">
                      <span className="w-2 h-2 rounded-full bg-[#00FF5B] animate-ping" />
                      Executing quant query...
                    </span>
                  ) : (
                    agentNarrative || <span className="text-slate-500">Type a query in the search bar above to trigger the agent.</span>
                  )}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 2: ODDS VIEW -- real multi-book comparison */}
      <AnimatePresence mode="wait">
        {activeTab === "odds" && (
          <motion.div key="odds" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <OddsCompare />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 3: ARBITRAGE VIEW -- real cross-book scan */}
      <AnimatePresence mode="wait">
        {activeTab === "arbitrage" && (
          <motion.div key="arbitrage" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <ArbitrageScanner />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 4: SIMULATION VIEW (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "simulation" && (
          <motion.div key="simulation" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 shadow-lg min-h-[400px] flex flex-col items-center justify-center gap-4">
            <Activity className="text-[#00FF5B] animate-pulse w-12 h-12 mb-2" />
            <h2 className="text-lg font-bold text-white uppercase tracking-widest">Monte Carlo Engine</h2>
            
            {dashboardData?.home_win_probability || dashboardData?.away_win_probability ? (
              <div className="w-full max-w-2xl mt-6">
                <div className="grid grid-cols-2 gap-6 text-center">
                  <div className="p-6 border border-[#1C212B] rounded-xl bg-[#06080A] shadow-inner shadow-[#00FF5B]/5">
                    <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">Home Win Probability</p>
                    <p className="text-3xl font-black text-[#00FF5B]">{dashboardData.home_win_probability}</p>
                  </div>
                  <div className="p-6 border border-[#1C212B] rounded-xl bg-[#06080A] shadow-inner shadow-[#00FF5B]/5">
                    <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">Away Win Probability</p>
                    <p className="text-3xl font-black text-[#00FF5B]">{dashboardData.away_win_probability}</p>
                  </div>
                </div>
                <div className="mt-6 p-4 border border-[#1C212B] rounded-xl bg-[#06080A] text-center">
                  <p className="text-xs text-slate-500 uppercase tracking-widest mb-1">Median Projected Score</p>
                  <p className="text-lg text-white font-bold">{dashboardData.median_projected_score || "N/A"}</p>
                </div>
              </div>
            ) : (
              <p className="text-slate-500 text-sm max-w-md text-center">
                Awaiting simulation parameters. Run a matchup query in the dashboard to populate the engine.
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 5: BET JOURNAL (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "journal" && (
          <motion.div key="journal" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <BetJournal />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 6: POWER RATINGS (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "ratings" && (
          <motion.div key="ratings" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <RatingsPanel />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 7: EDGE RADAR (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "radar" && (
          <motion.div key="radar" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <EdgeRadar />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 8: MODEL CALIBRATION (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "calibration" && (
          <motion.div key="calibration" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <Calibration />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 9: LINE MOVEMENT / AUTO-CLV (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "lines" && (
          <motion.div key="lines" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <LineMovement />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 10: DAILY SCHEDULE (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "schedule" && (
          <motion.div key="schedule" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <Schedule />
          </motion.div>
        )}
      </AnimatePresence>

      {/* TAB 11: STANDINGS / TEAM & PLAYER STATS (NEW) */}
      <AnimatePresence mode="wait">
        {activeTab === "stats" && (
          <motion.div key="stats" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
            <StatsPanel />
          </motion.div>
        )}
      </AnimatePresence>

    </main>
  );
}