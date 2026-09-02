"use client";
import { motion } from "framer-motion";

export default function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col"
    >
      <span className="text-xs text-slate-400">{label}</span>
      <span
        className={`text-lg font-bold ${
          accent ? "text-[#00FF5B]" : "text-white"
        }`}
      >
        {value}
      </span>
    </motion.div>
  );
}
