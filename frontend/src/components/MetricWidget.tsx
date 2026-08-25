import React, { memo } from 'react';

interface MetricWidgetProps {
  label: string;
  value: string | number;
  highlight?: boolean;
}

// React.memo prevents the widget from re-rendering unless its specific value changes
const MetricWidget = memo(({ label, value, highlight = false }: MetricWidgetProps) => {
  return (
    <div className={`bg-[#161b22] p-5 rounded-2xl shadow-[5px_5px_15px_#080a0e,-5px_-5px_15px_#1c222c] text-center flex flex-col justify-center transition-all duration-300 ${highlight ? 'border border-blue-500/30' : ''}`}>
      <div className="text-gray-400 text-xs mb-1 uppercase tracking-wider">{label}</div>
      <div className={`font-bold text-xl ${highlight ? 'text-blue-400' : 'text-[#e6edf3]'}`}>
        {value}
      </div>
    </div>
  );
});

MetricWidget.displayName = 'MetricWidget';
export default MetricWidget;
