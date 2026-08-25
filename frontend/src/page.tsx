"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { 
  Activity, 
  Shield, 
  Cpu, 
  BookOpen, 
  User, 
  Search, 
  Sparkles, 
  Terminal, 
  Compass, 
  Layers, 
  Sliders, 
  Globe, 
  BarChart3, 
  Send 
} from "lucide-react";

// ⚠️ Make sure this path matches where you created the components folder!
import { MonteCarloWidget, OddsWidget, PoissonWidget } from "./components/QuantWidgets";
import type { MonteCarloData, OddsData, PoissonData } from "./components/QuantWidgets";

type RiskProfile = "Conservative" | "Moderate" | "Aggressive";

type Message = {
  role: "user" | "assistant";
  content: string;
};

function extractQuantitativeJson(content: string): { data: Record<string, unknown>; raw: string } | null {
  const fencedMatch = content.match(/`{2,3}\s*(?:json)?\s*(\{[\s\S]*?\})\s*`{2,3}/i);
  if (fencedMatch) {
    try {
      return { data: JSON.parse(fencedMatch[1]) as Record<string, unknown>, raw: fencedMatch[0] };
    } catch {
      // Continue with direct object extraction while a streamed response is incomplete.
    }
  }

  const signature = /(\"(?:projected_home_lambda|median_projected_score|prediction_target)\"\s*:)/;
  const signatureMatch = content.match(signature);
  if (!signatureMatch || signatureMatch.index === undefined) return null;

  const start = content.lastIndexOf("{", signatureMatch.index);
  if (start < 0) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let index = start; index < content.length; index += 1) {
    const character = content[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') inString = false;
      continue;
    }
    if (character === '"') inString = true;
    else if (character === "{") depth += 1;
    else if (character === "}") {
      depth -= 1;
      if (depth === 0) {
        const raw = content.slice(start, index + 1);
        try {
          return { data: JSON.parse(raw) as Record<string, unknown>, raw };
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

function isPoissonData(data: Record<string, unknown>): data is PoissonData {
  return typeof data.projected_home_lambda === "number" && typeof data.projected_total_points === "number";
}

function isMonteCarloData(data: Record<string, unknown>): data is MonteCarloData {
  return typeof data.simulation_runs === "number" && typeof data.median_projected_score === "string";
}

function isOddsData(data: Record<string, unknown>): data is OddsData {
  return typeof data.prediction_target === "string" && typeof data.favored_team === "string";
}

export default function Dashboard() {
  const [bankroll, setBankroll] = useState(1025);
  const [riskProfile, setRiskProfile] = useState<RiskProfile>("Moderate");
  const [threadId, setThreadId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [searchFilter, setSearchFilter] = useState("All Models");
  const [selectedNav, setSelectedNav] = useState("Overview");

  const [metrics, setMetrics] = useState({
    units: 4.19,
    coverage: 74,
    edges: 490,
    delta: 0.99,
  });

  useEffect(() => {
    setThreadId(crypto.randomUUID());
  }, []);

  const chartData = useMemo(() => {
    const volatility = riskProfile === "Aggressive" ? 0.12 : riskProfile === "Moderate" ? 0.06 : 0.03;
    return Array.from({ length: 20 }, (_, index) => {
      const variation = Math.sin(index * 1.5) * volatility;
      return {
        day: `T-${20 - index}`,
        value: Math.max(0, bankroll * (1 + variation)),
      };
    });
  }, [bankroll, riskProfile]);

  const handleFilterClick = (filter: string) => {
    setSearchFilter(filter);
    if (filter === "+EV Odds") {
      setInput("Calculate +EV market edge and pricing discrepancies for ");
    } else if (filter === "Kelly Staking") {
      setInput("Determine optimal Kelly Criterion sizing for ");
    } else if (filter === "Poisson Matchup") {
      setInput("Run Monte Carlo probability simulation for ");
    } else {
      setInput("Analyze overall matchup and win probability for ");
    }
  };

  const handleSendMessage = async (customQuery?: string) => {
    const userPrompt = (customQuery || input).trim();
    if (!userPrompt || isLoading) return;

    const activeThreadId = threadId || crypto.randomUUID();
    if (!threadId) setThreadId(activeThreadId);

    setInput("");
    setIsLoading(true);

    setMessages((previous) => [
      ...previous,
      { role: "user", content: userPrompt },
      { role: "assistant", content: "" },
    ]);

    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/chat/sports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userPrompt,
          thread_id: activeThreadId,
          bankroll,
          risk_profile: riskProfile,
        }),
      });

      if (!response.ok) throw new Error(`Backend returned status ${response.status}`);
      if (!response.body) throw new Error("No response stream received");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accumulatedContent = "";

      const processEvent = (event: string) => {
        const data = event
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");

        if (!data) return false;
        if (data === "[DONE]") return true;

        try {
          const parsed = JSON.parse(data);
          if (parsed.type === "token") {
            accumulatedContent += String(parsed.content ?? "");
            updateAssistantMessage(accumulatedContent);
          }
          if (parsed.type === "metrics") {
            setMetrics((prev) => ({
              ...prev,
              units: parsed.units ?? prev.units,
              coverage: parsed.coverage ?? prev.coverage,
              edges: parsed.edges ?? prev.edges,
              delta: parsed.delta ?? prev.delta,
            }));
          }
        } catch {
          // Ignore parsing anomalies
        }
        return false;
      };

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        const events = buffer.split(/\r?\n\r?\n/);
        buffer = events.pop() ?? "";

        let streamFinished = false;
        for (const event of events) {
          if (processEvent(event)) {
            streamFinished = true;
            break;
          }
        }
        if (done || streamFinished) break;
      }
      if (buffer.trim()) processEvent(buffer);
    } catch (error) {
      console.error("Streaming error:", error);
      updateAssistantMessage("Error connecting to backend analytical stream.");
    } finally {
      setIsLoading(false);
    }
  };

  const updateAssistantMessage = (content: string) => {
    setMessages((previous) => {
      if (previous.length === 0) return previous;
      const updated = [...previous];
      updated[updated.length - 1] = { role: "assistant", content };
      return updated;
    });
  };

  return (
    <div className="terminal-shell select-none">
      
      {/* 1. ULTRA-SLIM ICON DOCK (Far Left) */}
      <aside className="icon-rail">
        <div className="flex flex-col items-center gap-6">
          <button className="brand-mark" onClick={() => setSelectedNav("Overview")} aria-label="Quant Terminal home" title="Quant Terminal home">
            Q<span>T</span>
          </button>
          <div className="rail-rule" />
          <div className="flex flex-col gap-3">
            {/* Nav buttons unchanged */}
            <button className={`rail-button ${selectedNav === "Overview" ? "active" : ""}`} onClick={() => setSelectedNav("Overview")}>
              <Compass size={20}/>
            </button>
            <button className={`rail-button ${selectedNav === "Performance" ? "active" : ""}`} onClick={() => setSelectedNav("Performance")}>
              <BarChart3 size={20}/>
            </button>
            <button className={`rail-button ${selectedNav === "Models" ? "active" : ""}`} onClick={() => setSelectedNav("Models")}>
              <Layers size={20}/>
            </button>
            <button className={`rail-button ${selectedNav === "Settings" ? "active" : ""}`} onClick={() => setSelectedNav("Settings")}>
              <Sliders size={20}/>
            </button>
            <button className={`rail-button ${selectedNav === "Global markets" ? "active" : ""}`} onClick={() => setSelectedNav("Global markets")}>
              <Globe size={20}/>
            </button>
          </div>
        </div>
        <div className="flex flex-col items-center gap-3">
          <button className="avatar" onClick={() => setSelectedNav("Profile")}>
            LG
          </button>
        </div>
      </aside>

      {/* 2. MAIN DASHBOARD CONTENT AREA */}
      <main className="dashboard-main">
        
        {/* Top Header Bar */}
        <header className="topbar">
          <div className="flex items-center gap-4">
            <h1 className="eyebrow">
              <span className="status-dot" /> QUANT TERMINAL <span className="muted">/</span> SPORTS INTELLIGENCE
            </h1>
          </div>

          <div className="topbar-actions">
            <span className="live-label"><span className="live-dot" /> LIVE FEED</span>
            <label className="control-field">
              <span>BANKROLL:</span>
              <span>$</span>
              <input type="number" value={bankroll} onChange={(e) => setBankroll(Number(e.target.value))} />
            </label>
            <div className="control-field">
              <span>RISK:</span>
              <select
                value={riskProfile}
                onChange={(e) => setRiskProfile(e.target.value as RiskProfile)}
                className="bg-transparent text-sm font-bold text-white outline-none cursor-pointer"
              >
                <option value="Conservative" className="bg-[#141620]">Conservative</option>
                <option value="Moderate" className="bg-[#141620]">Moderate</option>
                <option value="Aggressive" className="bg-[#141620]">Aggressive</option>
              </select>
            </div>
          </div>
        </header>

        {/* Cognitive Search Bar & Command Center */}
        <div className="panel search-panel">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-xs font-semibold text-[#d4af37] uppercase tracking-widest flex items-center gap-1.5">
              <Search size={14}/> Cognitive Outcome Predictor & Search Engine
            </span>
            <div className="flex gap-2">
              {["All Models", "+EV Odds", "Kelly Staking", "Poisson Matchup"].map((filter) => (
                <button
                  key={filter}
                  onClick={() => handleFilterClick(filter)}
                  className={`text-xs px-3 py-1 rounded-lg transition-all cursor-pointer font-medium ${
                    searchFilter === filter
                      ? "bg-gradient-to-r from-[#d4af37] to-[#b8972b] text-[#090a0d] font-bold shadow-[0_0_10px_rgba(212,175,55,0.3)]"
                      : "bg-[#141620] text-gray-400 hover:text-white border border-[#212533]"
                  }`}
                >
                  {filter}
                </button>
              ))}
            </div>
          </div>

          <div className="search-row">
            <Search className="absolute left-4 text-gray-500 pointer-events-none" size={18}/>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSendMessage();
              }}
              placeholder="Ask predictive model e.g., 'Analyze Chiefs vs 49ers spread & expected value'..."
              className="search-input"
            />
            <button
              type="button"
              onClick={() => void handleSendMessage()}
              disabled={isLoading}
              className="predict-button"
            >
              <Send size={14}/> Predict
            </button>
          </div>
        </div>

        {/* GRID LAYOUT (Bento Cards matching design aesthetic) */}
        <div className="workspace-grid">
          
          {/* Card 1: Variance Projection Chart */}
          <div className="panel chart-panel">
            {/* ... Chart code remains exactly the same ... */}
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                Simulated 30-Day Variance Projection
              </h2>
              <span className="text-xs text-[#d4af37] bg-[#d4af37]/10 px-2.5 py-0.5 rounded border border-[#d4af37]/20">
                Monte Carlo 10k Active
              </span>
            </div>

            <div className="chart-wrap">
              <ResponsiveContainer height="100%" width="100%">
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="goldGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#d4af37" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#d4af37" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#181b26" strokeDasharray="3 3"/>
                  <XAxis dataKey="day" hide/>
                  <YAxis domain={["auto", "auto"]} fontSize={11} stroke="#4b5563" tickFormatter={(val) => `$${val.toFixed(0)}`} />
                  <Tooltip contentStyle={{ backgroundColor: "#0e1017", borderColor: "#212533", borderRadius: "10px", color: "#fff" }} />
                  <Area dataKey="value" fill="url(#goldGradient)" fillOpacity={1} stroke="#d4af37" strokeWidth={2} type="monotone"/>
                </AreaChart>
              </ResponsiveContainer>
            </div>
            
            <div className="grid grid-cols-4 gap-3 mt-4 pt-4 border-t border-[#181b26] text-center">
              <div>
                <div className="text-[10px] text-gray-500 uppercase tracking-widest">Active Units</div>
                <div className="text-sm font-bold text-white">{metrics.units.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-500 uppercase tracking-widest">Coverage</div>
                <div className="text-sm font-bold text-white">{metrics.coverage}%</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-500 uppercase tracking-widest">Edges Found</div>
                <div className="text-sm font-bold text-[#d4af37]">{metrics.edges}</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-500 uppercase tracking-widest">Implied Delta</div>
                <div className="text-sm font-bold text-white">{metrics.delta.toFixed(2)}</div>
              </div>
            </div>
          </div>

          {/* Card 2: Agent Intelligence Stream (Terminal Output) */}
          <div className="panel command-panel">
            <h2 className="mb-4 flex items-center gap-2 text-sm font-bold text-white uppercase tracking-wider shrink-0 border-b border-[#181b26] pb-3">
              <Activity className="text-[#d4af37]" size={16}/>
              Agent Intelligence Stream
            </h2>

            <div className="flex-1 space-y-3 overflow-y-auto pr-1">
              {messages.length === 0 && (
                <div className="mt-20 text-center text-xs text-gray-500 px-4">
                  <Terminal className="mx-auto mb-2 opacity-30 text-[#d4af37]" size={28}/>
                  Select a filter or enter a prediction prompt in the search console above.
                </div>
              )}

              {/* ✨ WIDGET PARSING INJECTED HERE ✨ */}
              {messages.map((message, index) => {
                let cleanContent = message.content;
                let widgetData = null;
                let widgetType = null;

                const extractedJson = extractQuantitativeJson(message.content);

                if (extractedJson) {
                  try {
                    const parsed = extractedJson.data;
                    // Check signature to see which widget it belongs to
                    if (isPoissonData(parsed)) {
                      widgetType = "poisson";
                      widgetData = parsed;
                    } else if (isMonteCarloData(parsed)) {
                      widgetType = "monte_carlo";
                      widgetData = parsed;
                    } else if (isOddsData(parsed)) {
                      widgetType = "odds";
                      widgetData = parsed;
                    }
                    // Remove the raw JSON block from the text stream so only the widget shows
                    cleanContent = message.content.replace(extractedJson.raw, "").trim();
                  } catch (e) {
                    // Ignore incomplete JSON errors while the stream is actively typing
                  }
                }

                return (
                  <div
                    key={`${message.role}-${index}`}
                    className={`rounded-xl p-3 text-xs whitespace-pre-wrap break-words leading-relaxed ${
                      message.role === "user"
                        ? "ml-auto max-w-[90%] bg-[#d4af37]/10 border border-[#d4af37]/30 text-[#f5ebd0]"
                        : "mr-auto w-full max-w-[95%] bg-[#141620] border border-[#212533] text-gray-300 shadow-sm"
                    }`}
                  >
                    {/* Render the extracted widgets */}
                    {widgetType === "poisson" && widgetData && isPoissonData(widgetData) && <PoissonWidget data={widgetData} />}
                    {widgetType === "monte_carlo" && widgetData && isMonteCarloData(widgetData) && <MonteCarloWidget data={widgetData} />}
                    {widgetType === "odds" && widgetData && isOddsData(widgetData) && <OddsWidget data={widgetData} />}
                    
                    {/* Render whatever text is left (e.g. conversational wrapping) */}
                    {cleanContent && <div className="mt-2">{cleanContent}</div>}
                  </div>
                );
              })}

              {isLoading && messages[messages.length - 1]?.content === "" && (
                <div className="text-[11px] italic text-[#d4af37] flex items-center gap-2 p-2.5 bg-[#d4af37]/5 rounded-xl border border-[#d4af37]/20">
                  <span className="w-2 h-2 rounded-full bg-[#d4af37] animate-ping" /> Running multi-agent quantitative consensus...
                </div>
              )}
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}