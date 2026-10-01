import React from 'react';

interface Props {
  onBack: () => void;
}

export function TermsView({ onBack }: Props) {
  return (
    <div className="min-h-screen bg-[#0c1017] text-[#e4e6ec] p-6 max-w-3xl mx-auto">
      <button onClick={onBack} className="text-sm text-[#8a94a6] hover:text-white mb-6 flex items-center gap-1">
        <span className="material-symbols-outlined text-[18px]">arrow_back</span>
        Back
      </button>

      <h1 className="text-2xl font-bold text-white mb-2">Terms of Use</h1>
      <p className="text-sm text-[#8a94a6] mb-8">Last updated: 19 September 2026</p>

      <div className="space-y-6 text-sm leading-relaxed text-[#b0b8c8]">
        <section>
          <h2 className="text-base font-semibold text-white mb-2">1. Authorized Use</h2>
          <p>PEHCHAAN is a restricted-access system authorized exclusively for use by designated officers of the Bureau of Immigration, border security personnel, and checkpoint administrators. Unauthorized access is an offence under Section 66 of the Information Technology Act, 2000.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">2. User Responsibilities</h2>
          <ul className="list-disc list-inside space-y-1">
            <li>Protect login credentials; do not share accounts</li>
            <li>Use the system only for authorized screening operations at assigned checkpoints</li>
            <li>Report any system anomalies, suspected breaches, or unauthorized access immediately</li>
            <li>Do not attempt to extract, copy, or transmit screening data outside authorized channels</li>
            <li>Follow standard operating procedures for document handling and screening</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">3. System Scope</h2>
          <p>PEHCHAAN provides AI-assisted screening as a decision-support tool. All screening verdicts (CLEAR, REVIEW, HIGH RISK) are recommendations. Final decisions on document authenticity and traveler clearance rest with the authorized officer.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">4. Audit and Accountability</h2>
          <p>All user actions are logged in a tamper-evident audit trail. Screening decisions, logins, configuration changes, and escalations are recorded with timestamps, actor identity, and checkpoint context. Logs are subject to review by supervisory authorities.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">5. Availability</h2>
          <p>PEHCHAAN includes store-and-forward capability for operation in low-connectivity environments. The system may be unavailable during scheduled maintenance. Service interruptions do not relieve officers of their duty to perform manual document checks.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">6. Intellectual Property</h2>
          <p>PEHCHAAN is developed under Smart India Hackathon 2026, Problem Statement 26188. All intellectual property rights are vested with the Government of India.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">7. Governing Law</h2>
          <p>These terms are governed by the laws of India. Any disputes shall be subject to the exclusive jurisdiction of the courts in New Delhi.</p>
        </section>
      </div>
    </div>
  );
}