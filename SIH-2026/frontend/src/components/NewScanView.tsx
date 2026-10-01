import React, { useEffect, useRef, useState } from 'react';
import { DocumentType, ScreeningRecord, ScreenType } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { runScreening } from '../services/neonSyncService';
import { EvaluationMatrix, FacesCompared, RiskBreakdown, VerdictBadge, DOC_TYPE_LABELS, verdictTone } from './screening/ScreeningParts';

interface NewScanViewProps {
  onNavigate: (screen: ScreenType) => void;
  onAddRecord: (record: ScreeningRecord) => void;
  onSelectRecord: (record: ScreeningRecord) => void;
}

const DOC_OPTIONS: { id: DocumentType; label: string; desc: string; icon: string }[] = [
  { id: 'auto', label: 'Auto-detect', desc: 'Image classifier + printed-text markers decide', icon: 'auto_awesome' },
  { id: 'passport', label: 'Passport', desc: 'Reads and checks the 2-line MRZ', icon: 'menu_book' },
  { id: 'aadhaar', label: 'Aadhaar', desc: '12-digit UID with Verhoeff check', icon: 'badge' },
  { id: 'pan', label: 'PAN card', desc: 'ABCDE1234F format check', icon: 'credit_card' },
  { id: 'driving-licence', label: 'Driving licence', desc: 'State-RTO number format', icon: 'directions_car' },
  { id: 'visa', label: 'Visa', desc: 'Visa number, type, validity', icon: 'card_membership' },
  { id: 'permit', label: 'Border permit', desc: 'Permit number and validity', icon: 'receipt' },
  { id: 'national-id', label: 'Other national ID', desc: 'Generic ID card', icon: 'id_card' },
];

const STAGES = [
  'Identifying the document type',
  'Reading printed text and MRZ (Tesseract OCR)',
  'Checking the image for pasted or cloned regions',
  'Finding and comparing faces',
  'Comparing details with earlier screenings',
  'Calculating the risk score',
];

const MAX_SIDE = 3000;
// Serverless hosts cap a request body (Vercel: 4.5 MB). The document and the
// live photo travel together as base64, so each gets a share of that budget.
const DOC_BUDGET_CHARS = 2_900_000;
const LIVE_BUDGET_CHARS = 1_200_000;

// Re-encodes only as much as needed: recompression weakens the forensic signal.
function fitToBudget(source: CanvasImageSource, width: number, height: number, budget: number): string {
  let scale = 1;
  for (let attempt = 0; attempt < 8; attempt++) {
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    canvas.getContext('2d')!.drawImage(source, 0, 0, canvas.width, canvas.height);
    for (const quality of [0.92, 0.85, 0.78]) {
      const url = canvas.toDataURL('image/jpeg', quality);
      if (url.length <= budget || (attempt === 7 && quality === 0.78)) return url;
    }
    scale *= 0.85;
  }
  return '';
}

// Phone photos can be 12+ MP; cap the longest side so uploads stay small
// while keeping MRZ text large enough for OCR.
function prepareImage(dataUrl: string, budget = DOC_BUDGET_CHARS): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
      if (scale === 1 && dataUrl.startsWith('data:image/jpeg') && dataUrl.length <= budget) return resolve(dataUrl);
      resolve(fitToBudget(img, Math.round(img.width * scale), Math.round(img.height * scale), budget));
    };
    img.onerror = () => resolve(dataUrl);
    img.src = dataUrl;
  });
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export const NewScanView: React.FC<NewScanViewProps> = ({ onNavigate, onAddRecord, onSelectRecord }) => {
  const { user, checkpoint, token } = useAuth();
  const [selectedDoc, setSelectedDoc] = useState<DocumentType>('auto');
  const [docImage, setDocImage] = useState<string | null>(null);
  const [liveImage, setLiveImage] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScreeningRecord | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const docInputRef = useRef<HTMLInputElement>(null);
  const liveInputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const [cameraFor, setCameraFor] = useState<'doc' | 'live' | null>(null);
  const [cameraFacing, setCameraFacing] = useState<'environment' | 'user'>('environment');
  const [cameraError, setCameraError] = useState<string | null>(null);

  useEffect(() => {
    if (!isProcessing) return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 250);
    return () => clearInterval(timer);
  }, [isProcessing]);

  useEffect(() => () => stopCamera(), []);

  const stopCamera = () => {
    const stream = videoRef.current?.srcObject as MediaStream | null;
    stream?.getTracks().forEach((t) => t.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraFor(null);
    setCameraError(null);
  };

  const startCamera = async (target: 'doc' | 'live', facing: 'environment' | 'user') => {
    stopCamera();
    setCameraFor(target);
    setCameraFacing(facing);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported');
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
    } catch {
      setCameraError('Camera unavailable or permission denied. Use “Upload image” instead.');
    }
  };

  const capturePhoto = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const url = fitToBudget(video, video.videoWidth, video.videoHeight, cameraFor === 'doc' ? DOC_BUDGET_CHARS : LIVE_BUDGET_CHARS);
    if (cameraFor === 'doc') setDocImage(url);
    else setLiveImage(url);
    resetResult();
    stopCamera();
  };

  const resetResult = () => {
    setResult(null);
    setError(null);
  };

  const acceptFile = async (file: File | undefined, target: 'doc' | 'live') => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError('Please choose an image file (JPG or PNG). PDFs are not supported yet.');
      return;
    }
    const url = await readFile(file);
    if (target === 'doc') setDocImage(url);
    else setLiveImage(url);
    resetResult();
  };

  const execute = async () => {
    if (!docImage || !token || !checkpoint) return;
    setIsProcessing(true);
    setElapsed(0);
    resetResult();
    try {
      const [doc, live] = await Promise.all([prepareImage(docImage), liveImage ? prepareImage(liveImage, LIVE_BUDGET_CHARS) : null]);
      const record = await runScreening(
        { documentType: selectedDoc, documentImage: doc, liveImage: live, checkpointId: checkpoint.id },
        token,
      );
      setResult(record);
      onAddRecord(record);
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    } catch (err: any) {
      setError(err?.message || 'Screening failed.');
    } finally {
      setIsProcessing(false);
    }
  };

  const scanNext = () => {
    setDocImage(null);
    setLiveImage(null);
    setSelectedDoc('auto');
    resetResult();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const analysis = result?.analysis;
  const faceBox = analysis?.face.document_face_box;

  return (
    <div className="p-4 sm:p-6 space-y-6 max-w-[1400px] mx-auto">
      {cameraFor && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
          <div className="bg-[#111723] border border-[#202b3e] rounded-2xl overflow-hidden max-w-2xl w-full flex flex-col">
            <div className="p-3 border-b border-[#202b3e] flex items-center justify-between">
              <span className="text-white text-xs font-semibold">
                {cameraFor === 'doc' ? 'Photograph the document' : 'Photograph the traveller'}
              </span>
              <button onClick={stopCamera} className="text-[#94a3b8] hover:text-white p-1 rounded-lg" aria-label="Close camera">
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>
            <div className="relative aspect-[4/3] bg-black">
              <video ref={videoRef} playsInline autoPlay muted className="w-full h-full object-cover" />
              {!cameraError && (
                <div className="absolute inset-0 pointer-events-none flex items-center justify-center p-6">
                  <div
                    className={
                      cameraFor === 'doc'
                        ? 'border-2 border-dashed border-white/70 rounded-lg w-11/12 h-3/4'
                        : 'border-2 border-white/70 rounded-full h-4/5 aspect-[3/4]'
                    }
                  />
                </div>
              )}
              {cameraError && (
                <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-white text-sm">
                  {cameraError}
                </div>
              )}
            </div>
            <div className="p-3 bg-[#0c1017] flex items-center justify-between gap-2">
              <button
                onClick={() => startCamera(cameraFor, cameraFacing === 'environment' ? 'user' : 'environment')}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[#182133] text-[#cbd5e1] text-xs font-semibold"
              >
                <span className="material-symbols-outlined text-[18px]">flip_camera_ios</span>
                Switch camera
              </button>
              <button
                onClick={capturePhoto}
                disabled={!!cameraError}
                className="flex-1 max-w-xs flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-[#0059b5] hover:bg-[#00458f] disabled:opacity-40 text-white text-xs font-bold"
              >
                <span className="material-symbols-outlined text-[20px]">photo_camera</span>
                Capture
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3 pb-4 border-b border-[#efedf3]">
        <div>
          <h1 className="text-xl font-bold text-[#1a1b1f]">New screening</h1>
          <p className="text-xs text-[#414753] mt-0.5">
            {checkpoint?.name} · Officer {user?.name}
          </p>
        </div>
        <button
          onClick={() => onNavigate('overview')}
          className="self-start sm:self-auto px-3 py-1.5 text-xs text-[#414753] bg-[#f4f3f8] hover:bg-[#efedf3] rounded-md"
        >
          Back to dashboard
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
        <div className="xl:col-span-3 space-y-6">
          {/* Step 1 */}
          <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
            <StepTitle n={1} title="Document type" hint="Leave on Auto-detect if unsure" />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {DOC_OPTIONS.map((opt) => {
                const active = selectedDoc === opt.id;
                return (
                  <button
                    key={opt.id}
                    onClick={() => { setSelectedDoc(opt.id); resetResult(); }}
                    className={`p-2.5 rounded-lg text-left border transition-colors ${
                      active ? 'border-[#0059b5] bg-[#eef3ff] ring-1 ring-[#0059b5]' : 'border-[#efedf3] hover:border-[#c1c6d6] bg-[#fbfbfe]'
                    }`}
                  >
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-[#1a1b1f]">
                      <span className={`material-symbols-outlined text-[17px] ${active ? 'text-[#0059b5]' : 'text-[#717785]'}`}>{opt.icon}</span>
                      {opt.label}
                    </div>
                    <p className="text-[10.5px] text-[#717785] mt-1 leading-snug">{opt.desc}</p>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Step 2 */}
          <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
            <StepTitle n={2} title="Document image" hint="JPG or PNG, flat and in focus" />
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); acceptFile(e.dataTransfer.files?.[0], 'doc'); }}
              className={`relative rounded-lg border-2 border-dashed overflow-hidden bg-[#f4f3f8] min-h-[220px] flex items-center justify-center ${
                dragOver ? 'border-[#0059b5] bg-[#eef3ff]' : 'border-[#c1c6d6]'
              }`}
            >
              {docImage ? (
                <div className="relative inline-block max-w-full">
                  <img src={docImage} alt="Document to screen" className="block max-h-[420px] max-w-full object-contain" />
                  {faceBox && (
                    <div
                      className="absolute border-2 border-[#0059b5] bg-[#0059b5]/10 rounded-sm pointer-events-none"
                      style={{
                        left: `${(faceBox.x / faceBox.image_w) * 100}%`,
                        top: `${(faceBox.y / faceBox.image_h) * 100}%`,
                        width: `${(faceBox.w / faceBox.image_w) * 100}%`,
                        height: `${(faceBox.h / faceBox.image_h) * 100}%`,
                      }}
                    >
                      <span className="absolute -top-5 left-0 bg-[#0059b5] text-white text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap">
                        Face detected
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                <button onClick={() => docInputRef.current?.click()} className="flex flex-col items-center gap-2 p-6 text-center">
                  <span className="material-symbols-outlined text-[40px] text-[#0059b5]">upload_file</span>
                  <span className="text-sm font-semibold text-[#1a1b1f]">Drop the document image here</span>
                  <span className="text-xs text-[#717785]">or choose a file</span>
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => docInputRef.current?.click()} className="btn-secondary">
                <span className="material-symbols-outlined text-[16px]">upload</span> Upload image
              </button>
              <button onClick={() => startCamera('doc', 'environment')} className="btn-secondary">
                <span className="material-symbols-outlined text-[16px]">photo_camera</span> Use camera
              </button>
              {docImage && (
                <button onClick={() => { setDocImage(null); resetResult(); }} className="btn-ghost">
                  Remove
                </button>
              )}
              <input ref={docInputRef} type="file" accept="image/*" className="hidden"
                onChange={(e) => { acceptFile(e.target.files?.[0], 'doc'); e.target.value = ''; }} />
            </div>
          </section>

          {/* Step 3 */}
          <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
            <StepTitle n={3} title="Live photo of the traveller" hint="Optional — enables face matching" />
            <div className="flex flex-col sm:flex-row gap-4 items-start">
              <div className="w-32 h-40 rounded-lg overflow-hidden bg-[#f4f3f8] border border-[#efedf3] flex items-center justify-center shrink-0">
                {liveImage ? (
                  <img src={liveImage} alt="Live capture" className="w-full h-full object-cover" />
                ) : (
                  <span className="material-symbols-outlined text-[36px] text-[#c1c6d6]">face</span>
                )}
              </div>
              <div className="space-y-2">
                <p className="text-xs text-[#414753] leading-relaxed max-w-md">
                  The face on the document is compared with this photo. Without it, the face check is left out and
                  the other checks carry the score.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => startCamera('live', 'user')} className="btn-secondary">
                    <span className="material-symbols-outlined text-[16px]">videocam</span> Take photo
                  </button>
                  <button onClick={() => liveInputRef.current?.click()} className="btn-secondary">
                    <span className="material-symbols-outlined text-[16px]">add_a_photo</span> Upload photo
                  </button>
                  {liveImage && (
                    <button onClick={() => { setLiveImage(null); resetResult(); }} className="btn-ghost">Remove</button>
                  )}
                  <input ref={liveInputRef} type="file" accept="image/*" className="hidden"
                    onChange={(e) => { acceptFile(e.target.files?.[0], 'live'); e.target.value = ''; }} />
                </div>
              </div>
            </div>
          </section>
        </div>

        {/* Right column: run + result */}
        <div className="xl:col-span-2 space-y-4 xl:sticky xl:top-4 self-start" ref={resultRef}>
          <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-4">
            <StepTitle n={4} title="Run screening" />
            {!result && (
              <button
                onClick={execute}
                disabled={!docImage || isProcessing}
                className="w-full bg-[#0059b5] hover:bg-[#00458f] disabled:bg-[#c1c6d6] disabled:cursor-not-allowed text-white py-3 rounded-xl text-sm font-bold flex items-center justify-center gap-2"
              >
                <span className={`material-symbols-outlined text-[20px] ${isProcessing ? 'animate-spin' : ''}`}>
                  {isProcessing ? 'progress_activity' : 'policy'}
                </span>
                {isProcessing ? `Screening… ${elapsed}s` : docImage ? 'Screen this document' : 'Add a document image first'}
              </button>
            )}

            {isProcessing && (
              <ul className="space-y-1.5 text-xs text-[#414753]" aria-live="polite">
                {STAGES.map((s) => (
                  <li key={s} className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#0059b5] animate-pulse" />
                    {s}
                  </li>
                ))}
                <li className="text-[11px] text-[#717785] pt-1">These checks run in parallel; a scan usually takes 1–8 seconds.</li>
              </ul>
            )}

            {error && (
              <div className="p-3 rounded-lg bg-[#fff1f0] border border-[#ffdad6] text-xs text-[#93000a] flex gap-2">
                <span className="material-symbols-outlined text-[18px]">error</span>
                <span>{error}</span>
              </div>
            )}

            {result && analysis && (
              <div className="space-y-4">
                <div className={`rounded-xl p-4 ${verdictTone(result.riskVerdict).panel}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <VerdictBadge verdict={result.riskVerdict} />
                      <div className="text-xs mt-2 opacity-90">{result.docCode} · {result.presenterName}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-4xl font-extrabold font-mono leading-none">{result.riskScore}</div>
                      <div className="text-[10px] uppercase tracking-wider mt-1 opacity-80">risk / 100</div>
                    </div>
                  </div>
                </div>

                <EvaluationMatrix rows={analysis.evaluation} compact />

                {(analysis.face.attempted || analysis.face.document_face_thumb) && <FacesCompared face={analysis.face} />}

                {analysis.risk.overrides.length > 0 && (
                  <div className="text-[11px] bg-[#fff1f0] border border-[#ffdad6] text-[#93000a] rounded-lg p-2.5 space-y-1">
                    {analysis.risk.overrides.map((o) => <div key={o}><span className="font-semibold">Why the score is high: </span>{o}</div>)}
                  </div>
                )}

                {analysis.classification && (
                  <div className="text-xs text-[#414753] bg-[#f4f3f8] rounded-lg p-3">
                    <span className="font-semibold text-[#1a1b1f]">
                      {selectedDoc === 'auto' ? 'Detected: ' : 'Screened as: '}
                      {DOC_TYPE_LABELS[analysis.classification.used_type] || analysis.classification.used_type}
                    </span>
                    {selectedDoc === 'auto' && ` (${Math.round(analysis.classification.confidence * 100)}% confidence)`}
                    <div className="text-[11px] text-[#717785] mt-0.5">{analysis.classification.reason}</div>
                  </div>
                )}

                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                  <Field label="Name" value={analysis.identity.name} />
                  <Field label="Document no." value={analysis.identity.document_number} mono />
                  <Field label="Date of birth" value={analysis.identity.date_of_birth} mono />
                  <Field label="Expiry" value={analysis.identity.expiry_date} mono />
                </dl>

                <RiskBreakdown analysis={analysis} compact />

                <div className="text-[11px] text-[#717785] flex items-center justify-between border-t border-[#efedf3] pt-2">
                  <span>Saved · block {result.blockHeight}</span>
                  <span className="font-mono">{result.hashProof}</span>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => { onSelectRecord(result); onNavigate('screening-report'); }}
                    className="flex-1 bg-[#0059b5] hover:bg-[#00458f] text-white py-2.5 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5"
                  >
                    <span className="material-symbols-outlined text-[16px]">assignment</span> Full report
                  </button>
                  <button onClick={scanNext} className="flex-1 bg-[#f4f3f8] hover:bg-[#efedf3] text-[#1a1b1f] py-2.5 rounded-xl text-xs font-bold">
                    Screen next
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
};

const StepTitle: React.FC<{ n: number; title: string; hint?: string }> = ({ n, title, hint }) => (
  <div className="flex items-center justify-between gap-2">
    <div className="flex items-center gap-2.5">
      <span className="w-6 h-6 rounded-full bg-[#0059b5] text-white flex items-center justify-center font-bold text-xs">{n}</span>
      <h2 className="text-sm font-bold text-[#1a1b1f]">{title}</h2>
    </div>
    {hint && <span className="text-[11px] text-[#717785] text-right">{hint}</span>}
  </div>
);

const Field: React.FC<{ label: string; value?: string | null; mono?: boolean }> = ({ label, value, mono }) => (
  <div>
    <dt className="text-[10px] uppercase tracking-wide text-[#717785]">{label}</dt>
    <dd className={`text-[#1a1b1f] font-semibold break-words ${mono ? 'font-mono' : ''}`}>
      {value || <span className="text-[#a0a4ad] font-normal">Not read</span>}
    </dd>
  </div>
);
