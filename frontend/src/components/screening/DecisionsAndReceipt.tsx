import React, { useState } from 'react';
import { DecisionRecord, ScanReceipt } from '../../types';

const DECISION_TEXT: Record<DecisionRecord['decision'], string> = {
  clear: 'Clear traveller',
  secondary: 'Refer to secondary check',
  reject: 'Reject document',
};

const STATUS: Record<DecisionRecord['status'], { text: string; cls: string }> = {
  final: { text: 'Recorded', cls: 'bg-[#e9e7ed] text-[#414753]' },
  pending_cosign: { text: 'Awaiting In-Charge co-signature', cls: 'bg-[#ffe4af] text-[#5c3a00]' },
  cosigned: { text: 'Co-signed', cls: 'bg-[#dcf5e1] text-[#00531d]' },
  cosign_refused: { text: 'Refused by In-Charge', cls: 'bg-[#ffdad6] text-[#93000a]' },
};

/** Officer decisions on one record, with the two-person rule for overriding a flagged verdict. */
export const DecisionList: React.FC<{
  decisions: DecisionRecord[] | null;
  canCosign: boolean;
  currentUserId?: string;
  onCosign: (id: number, approve: boolean, notes: string) => Promise<void>;
}> = ({ decisions, canCosign, currentUserId, onCosign }) => {
  const [open, setOpen] = useState<number | null>(null);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (decisions === null) return <p className="text-xs text-[#717785]">Loading decisions…</p>;
  if (decisions.length === 0) return <p className="text-xs text-[#717785]">No officer decision recorded yet.</p>;

  const act = async (id: number, approve: boolean) => {
    setBusy(true); setError(null);
    try { await onCosign(id, approve, notes); setOpen(null); setNotes(''); }
    catch (e: any) { setError(e.message); }
    setBusy(false);
  };

  return (
    <ol className="space-y-3">
      {decisions.map((d) => (
        <li key={d.id} className="border border-[#efedf3] rounded-lg p-3 text-xs space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-[#1a1b1f]">{DECISION_TEXT[d.decision]}</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${STATUS[d.status].cls}`}>{STATUS[d.status].text}</span>
            <span className="text-[#717785]">by {d.officer} · {new Date(d.created_at).toLocaleString('en-IN')}</span>
          </div>
          <div className="text-[#414753]">System said {d.system_verdict} ({d.system_score}/100).{d.notes ? ` Reason: ${d.notes}` : ''}</div>
          {d.cosigner && (
            <div className="text-[#414753]">
              {d.status === 'cosigned' ? 'Co-signed' : 'Refused'} by <b>{d.cosigner}</b>
              {d.cosigned_at ? ` · ${new Date(d.cosigned_at).toLocaleString('en-IN')}` : ''}{d.cosign_notes ? ` — ${d.cosign_notes}` : ''}
            </div>
          )}
          {d.status === 'pending_cosign' && canCosign && d.officer_uid !== currentUserId && (
            open === d.id ? (
              <div className="space-y-2 pt-1">
                <label htmlFor={`cosign-${d.id}`} className="block text-[11px] font-semibold">What did you check before deciding?</label>
                <textarea id={`cosign-${d.id}`} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                  className="w-full text-xs p-2 border border-[#e3e2e7] rounded-lg focus:outline-none focus:border-[#0059b5]" />
                {error && <p className="text-[#93000a]">{error}</p>}
                <div className="flex gap-2">
                  <button disabled={busy || !notes.trim()} onClick={() => act(d.id, true)} className="px-3 py-1.5 rounded-md bg-[#006a26] text-white font-semibold disabled:opacity-40">Co-sign clearance</button>
                  <button disabled={busy || !notes.trim()} onClick={() => act(d.id, false)} className="px-3 py-1.5 rounded-md bg-[#ba1a1a] text-white font-semibold disabled:opacity-40">Refuse</button>
                  <button onClick={() => setOpen(null)} className="btn-ghost">Cancel</button>
                </div>
              </div>
            ) : (
              <button onClick={() => setOpen(d.id)} className="btn-secondary">Review override</button>
            )
          )}
          {d.status === 'pending_cosign' && d.officer_uid === currentUserId && (
            <p className="text-[11px] text-[#717785]">A different Post In-Charge or Admin must co-sign this.</p>
          )}
        </li>
      ))}
    </ol>
  );
};

/** The record's Merkle receipt and a one-click independent check of it. */
export const ReceiptPanel: React.FC<{ receipt: ScanReceipt | null }> = ({ receipt }) => {
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  if (!receipt) return <p className="text-xs text-[#717785]">Loading receipt…</p>;
  if (!receipt.sealed) {
    return <p className="text-xs text-[#717785]">Not sealed yet — records are sealed into a signed batch every 10 minutes.</p>;
  }
  const verify = async () => {
    setBusy(true);
    try {
      const res = await fetch('/api/public/verify-receipt', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(receipt),
      });
      setResult(await res.json());
    } finally { setBusy(false); }
  };
  const download = () => {
    const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `receipt-${receipt.scanId}.json`; a.click();
    URL.revokeObjectURL(url);
  };
  const b = receipt.batch!;
  return (
    <div className="space-y-3 text-xs">
      <p className="text-[#414753]">
        Sealed in batch <b>#{b.id}</b> ({b.leaf_count} records) on {new Date(b.sealed_at).toLocaleString('en-IN')}. The receipt
        rebuilds the batch's signed Merkle root from this record's hash and {receipt.path!.length} sibling hash(es) — so it proves this
        record existed unchanged at that time without revealing any other record.
      </p>
      <dl className="grid grid-cols-1 gap-1 font-mono text-[10.5px] break-all">
        <div><dt className="inline text-[#717785] font-sans">Record hash: </dt><dd className="inline">{receipt.leaf}</dd></div>
        <div><dt className="inline text-[#717785] font-sans">Merkle root: </dt><dd className="inline">{b.merkle_root}</dd></div>
        {b.external_proof && <div><dt className="inline text-[#717785] font-sans">Public timestamp: </dt><dd className="inline">OpenTimestamps proof attached</dd></div>}
      </dl>
      <div className="flex gap-2">
        <button onClick={verify} disabled={busy} className="btn-secondary">{busy ? 'Checking…' : 'Verify receipt'}</button>
        <button onClick={download} className="btn-ghost">Download receipt</button>
      </div>
      {result && (
        <div className={`p-2.5 rounded-lg ${result.valid && result.trustedKey ? 'bg-[#dcf5e1] text-[#00531d]' : 'bg-[#ffdad6] text-[#93000a]'}`}>
          {result.valid
            ? `Valid: the path rebuilds the signed root and the Ed25519 signature checks out${result.trustedKey ? ' with this server\'s key' : ' (signed by a different key)'}.`
            : `Invalid: ${result.error || (result.rootMatches ? 'signature does not verify' : 'path does not rebuild the root')}.`}
        </div>
      )}
    </div>
  );
};
