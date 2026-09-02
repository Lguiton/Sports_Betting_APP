"use client";
import { motion } from "framer-motion";

export default function MarketEdgeWidget({ data }: { data: any }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="flex flex-col gap-2"
    >
      <p className="text-[#00FF5B] font-bold text-lg">
        {data.edge_pct ? `${data.edge_pct}% Edge` : "No edge data"}
      </p>
      <p className="text-slate-400 text-sm">
        Best Book: {data.best_book ?? "N/A"}
      </p>
      <p className="text-slate-400 text-sm">
        Expected Value: {data.expected_value ?? "N/A"}
      </p>
    </motion.div>
  );
}