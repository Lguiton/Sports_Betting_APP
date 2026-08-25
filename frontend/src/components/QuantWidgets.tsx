export type PoissonData = {
  projected_home_lambda: number;
  projected_away_lambda: number;
  projected_total_points: number;
  vegas_line: number;
  over_probability_pct: number;
  under_probability_pct: number;
  edge_recommendation: string;
};

export type MonteCarloData = {
  simulation_runs: number;
  matchup: string;
  home_win_probability: string;
  away_win_probability: string;
  median_projected_score: string;
};

export type OddsData = {
  prediction_target?: string;
  favored_team?: string;
  win_probability?: string;
  projected_score?: string;
  market_edge?: string;
};

export function PoissonWidget({ data }: { data: PoissonData }) {
  return (
    <div className="quant-widget">
      <div className="quant-widget-title">POISSON TOTALS</div>
      <div className="quant-widget-grid">
        <span>PROJECTED TOTAL <strong>{data.projected_total_points}</strong></span>
        <span>VEGAS LINE <strong>{data.vegas_line}</strong></span>
        <span>OVER <strong className="widget-positive">{data.over_probability_pct}%</strong></span>
        <span>UNDER <strong>{data.under_probability_pct}%</strong></span>
      </div>
      <div className="quant-widget-result">{data.edge_recommendation}</div>
    </div>
  );
}

export function MonteCarloWidget({ data }: { data: MonteCarloData }) {
  return (
    <div className="quant-widget">
      <div className="quant-widget-title">MONTE CARLO / {data.simulation_runs.toLocaleString()} RUNS</div>
      <div className="quant-widget-grid">
        <span>MATCHUP <strong>{data.matchup}</strong></span>
        <span>PROJECTED SCORE <strong>{data.median_projected_score}</strong></span>
        <span>HOME WIN <strong className="widget-positive">{data.home_win_probability}</strong></span>
        <span>AWAY WIN <strong>{data.away_win_probability}</strong></span>
      </div>
    </div>
  );
}

export function OddsWidget({ data }: { data: OddsData }) {
  return (
    <div className="quant-widget">
      <div className="quant-widget-title">MATCHUP PREDICTION</div>
      <div className="quant-widget-grid">
        <span>MATCHUP <strong>{data.prediction_target ?? "Current matchup"}</strong></span>
        <span>FAVORED <strong>{data.favored_team ?? "Pending"}</strong></span>
        <span>WIN PROBABILITY <strong className="widget-positive">{data.win_probability ?? "N/A"}</strong></span>
        <span>PROJECTED SCORE <strong>{data.projected_score ?? "N/A"}</strong></span>
      </div>
      {data.market_edge && <div className="quant-widget-result">{data.market_edge}</div>}
    </div>
  );
}
