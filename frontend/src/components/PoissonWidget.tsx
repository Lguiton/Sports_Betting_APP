"use client";
import { motion } from "framer-motion";

export default function PoissonWidget({ data }: { data: any }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="flex flex-col gap-2"
    >
      <p className="text-[#00FF5B] font-bold text-lg">
        Total Points: {data.projected_total_points ?? "N/A"}
      </p>
      <p className="text-slate-400 text-sm">
        Over Probability: {data.over_probability_pct ?? "N/A"}%
      </p>
      <p className="text-slate-400 text-sm">
        Edge: {data.edge_recommendation ?? "N/A"}
      </p>
    </motion.div>
  );
}
