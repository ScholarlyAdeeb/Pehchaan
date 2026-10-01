import React, { useState, useEffect } from 'react';

export const LiveClock: React.FC<{ className?: string }> = ({ className }) => {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const time = now.toLocaleTimeString('en-IN', { hour12: false });
  const date = now.toLocaleDateString('en-IN', {
    weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
  });

  return (
    <div className={className}>
      <div className="text-2xl font-bold font-mono text-white tracking-wider">{time}</div>
      <div className="text-xs text-white/70 mt-0.5">{date}</div>
    </div>
  );
};
