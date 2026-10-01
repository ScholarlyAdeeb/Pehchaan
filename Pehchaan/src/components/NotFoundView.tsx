import React from 'react';

interface Props {
  onGoHome: () => void;
}

export function NotFoundView({ onGoHome }: Props) {
  return (
    <div className="min-h-screen bg-[#0c1017] flex items-center justify-center p-6">
      <div className="text-center max-w-md">
        <div className="text-7xl font-bold text-[#2563eb] mb-4 font-mono">404</div>
        <h1 className="text-xl font-semibold text-white mb-2">Page Not Found</h1>
        <p className="text-sm text-[#8a94a6] mb-8">
          The requested resource does not exist or you do not have authorization to access it.
        </p>
        <button
          onClick={onGoHome}
          className="px-6 py-2.5 bg-[#2563eb] text-white text-sm font-medium rounded-lg hover:bg-[#1d4fd8] transition-colors"
        >
          Return to Dashboard
        </button>
        <p className="text-xs text-[#5a6070] mt-6">
          If you believe this is an error, contact your system administrator.
        </p>
      </div>
    </div>
  );
}