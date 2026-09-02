import { create } from "zustand";

interface DashboardState {
  riskProfile: "Conservative" | "Moderate" | "Aggressive";
  setRiskProfile: (profile: "Conservative" | "Moderate" | "Aggressive") => void;
  activeTab: "dashboard" | "odds" | "arbitrage" | "simulation" | "journal" | "ratings" | "radar" | "calibration" | "lines" | "schedule" | "stats";
  setActiveTab: (tab: "dashboard" | "odds" | "arbitrage" | "simulation" | "journal" | "ratings" | "radar" | "calibration" | "lines" | "schedule" | "stats") => void;
  dashboardData: any;
  setDashboardData: (data: any) => void;
  agentNarrative: string;
  appendNarrative: (text: string) => void;
  clearNarrative: () => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  liveOddsFeed: any[];
  setLiveOddsFeed: (odds: any[]) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  riskProfile: "Moderate",
  setRiskProfile: (riskProfile) => set({ riskProfile }),
  activeTab: "dashboard",
  setActiveTab: (activeTab) => set({ activeTab }),
  dashboardData: {},
  setDashboardData: (dashboardData) => set({ dashboardData }),
  agentNarrative: "",
  appendNarrative: (text) => set((state) => ({ agentNarrative: state.agentNarrative + text })),
  clearNarrative: () => set({ agentNarrative: "" }),
  isLoading: false,
  setIsLoading: (isLoading) => set({ isLoading }),
  liveOddsFeed: [],
  setLiveOddsFeed: (liveOddsFeed) => set({ liveOddsFeed }),
}));
