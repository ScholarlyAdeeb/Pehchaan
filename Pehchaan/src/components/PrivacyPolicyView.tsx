import React from 'react';

interface Props {
  onBack: () => void;
}

export function PrivacyPolicyView({ onBack }: Props) {
  return (
    <div className="min-h-screen bg-[#0c1017] text-[#e4e6ec] p-6 max-w-3xl mx-auto">
      <button onClick={onBack} className="text-sm text-[#8a94a6] hover:text-white mb-6 flex items-center gap-1">
        <span className="material-symbols-outlined text-[18px]">arrow_back</span>
        Back
      </button>

      <h1 className="text-2xl font-bold text-white mb-2">Privacy Policy</h1>
      <p className="text-sm text-[#8a94a6] mb-8">Last updated: 19 September 2026</p>

      <div className="space-y-6 text-sm leading-relaxed text-[#b0b8c8]">
        <section>
          <h2 className="text-base font-semibold text-white mb-2">1. Data Controller</h2>
          <p>PEHCHAAN is operated by the Bureau of Immigration, Ministry of Home Affairs, Government of India, for the purpose of identity and document screening at authorized border checkpoints.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">2. Data We Process</h2>
          <ul className="list-disc list-inside space-y-1">
            <li>Identity document images (passport, visa, Aadhaar, driving license, permit) uploaded during screening</li>
            <li>Extracted text fields: name, document number, nationality, date of birth, MRZ data</li>
            <li>Biometric data: facial photograph for identity verification</li>
            <li>Screening results: risk score, verdict, evidence markers</li>
            <li>Officer credentials and session data for access control</li>
            <li>Audit logs: timestamps, actions, checkpoint identifiers</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">3. Legal Basis</h2>
          <p>Processing is carried out under the authority of the Passport (Entry into India) Act, 1920, the Foreigners Act, 1946, and the Information Technology Act, 2000, for the purpose of national border security and immigration control.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">4. Data Retention</h2>
          <p>Screening records are retained in accordance with Bureau of Immigration data retention policies. Audit logs are retained for a minimum of 5 years. Session tokens expire after 8 hours.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">5. Data Security</h2>
          <ul className="list-disc list-inside space-y-1">
            <li>All data is encrypted in transit (TLS 1.3) and at rest</li>
            <li>HMAC-SHA256 signed audit trail ensures tamper-evident logging</li>
            <li>SHA-256 hash chain provides blockchain-grade integrity verification</li>
            <li>Role-based access control (RBAC) enforced server-side</li>
            <li>Session fingerprinting prevents token replay attacks</li>
            <li>Rate limiting protects against brute-force authentication attempts</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">6. Data Sharing</h2>
          <p>Screening data is shared only with authorized government agencies as required by law. No data is shared with private third parties or transferred outside India.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">7. Rights of Data Subjects</h2>
          <p>Individuals screened at border checkpoints may request access to their screening records through the Bureau of Immigration's existing RTI and grievance mechanisms, subject to national security exemptions under the Digital Personal Data Protection Act, 2023.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-white mb-2">8. Contact</h2>
          <p>For privacy-related queries: Data Protection Officer, Bureau of Immigration, Ministry of Home Affairs, New Delhi.</p>
        </section>
      </div>
    </div>
  );
}