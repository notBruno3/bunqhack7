import { useEffect, useRef } from 'react'
import { Shield, ShieldAlert, Fingerprint, Activity, AlertTriangle, CheckCircle2, MicOff, Video } from 'lucide-react'
import type { AudioSource } from '../hooks/useAudioCapture'
import type {
  GeminiSummary,
  HumeScores,
  QuestionTurn,
  Tier,
  VerificationQuestion,
} from '../types'

interface Props {
  tier: Tier
  humeScores: HumeScores | null
  geminiSummary: GeminiSummary | null
  countdown: number
  videoStream: MediaStream | null
  audioSource: AudioSource
  merchant?: string
  turns: QuestionTurn[]
  currentQuestion: VerificationQuestion | null
}

const PURPOSE_LABELS: Record<QuestionTurn['purpose'], string> = {
  baseline: 'Baseline',
  intent: 'Intent',
  context: 'Context',
  knowledge_check: 'Knowledge',
  stress_probe: 'Stress probe',
}

function turnStatusLabel(t: QuestionTurn): { text: string; color: string } {
  switch (t.status) {
    case 'pending':   return { text: 'Pending',   color: '#4B5563' }
    case 'speaking':  return { text: 'Speaking',  color: '#60A5FA' }
    case 'listening': return { text: 'Listening', color: '#FBBF24' }
    case 'scoring':   return { text: 'Analyzing', color: '#A78BFA' }
    case 'done':      return { text: 'Scored',    color: '#4ADE80' }
  }
}

const BARS = [
  { key: 'calmness' as const, label: 'Calm', color: 'bg-emerald-500', barGlow: 'shadow-[0_0_10px_rgba(16,185,129,0.5)]' },
  { key: 'fear' as const, label: 'Fear', color: 'bg-red-500', barGlow: 'shadow-[0_0_10px_rgba(239,68,68,0.5)]' },
  { key: 'distress' as const, label: 'Distress', color: 'bg-orange-500', barGlow: 'shadow-[0_0_10px_rgba(249,115,22,0.5)]' },
  { key: 'anxiety' as const, label: 'Anxiety', color: 'bg-amber-400', barGlow: 'shadow-[0_0_10px_rgba(251,191,36,0.5)]' },
]

export default function VerifyingScreen({
  tier,
  humeScores,
  geminiSummary,
  countdown,
  videoStream,
  audioSource,
  merchant,
  turns,
  currentQuestion,
}: Props) {
  const selfViewRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    if (selfViewRef.current && videoStream) {
      selfViewRef.current.srcObject = videoStream
      selfViewRef.current.play().catch(() => {})
    }
  }, [videoStream])

  // Phase 2: "processing" now means: all turns done OR (no turns yet, ready event still pending)
  const allDone = turns.length > 0 && turns.every((t) => t.status === 'done')
  const isProcessing = !currentQuestion && (allDone || turns.length === 0)
  const isVideo = tier === 'HIGH_RISK'
  const timerStr = `0:${Math.max(0, countdown).toString().padStart(2, '0')}`

  return (
    <div className="flex flex-col h-full bg-[#050505] text-white overflow-hidden relative">
      
      {/* Dynamic background effect based on signals */}
      <div className={`absolute inset-0 transition-opacity duration-1000 ease-in-out pointer-events-none opacity-20
        ${humeScores?.verdict_hint === 'FLAGGED' ? 'bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-red-600 via-transparent to-transparent' :
          humeScores?.verdict_hint === 'CLEAN' ? 'bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-emerald-600 via-transparent to-transparent' :
          'bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-indigo-600 via-transparent to-transparent'
        }`}
      />

      {/* Self-view inset */}
      {isVideo && (
        <div className="absolute top-14 right-5 z-30 w-28 h-36 rounded-2xl overflow-hidden shadow-2xl border border-white/10 bg-black/50 backdrop-blur-sm">
          {videoStream ? (
            <video
              ref={selfViewRef}
              autoPlay
              muted
              playsInline
              className="w-full h-full object-cover scale-x-[-1]"
            />
          ) : (
            <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-gray-500">
              <Video size={24} />
              <span className="text-[10px] font-semibold">Camera off</span>
            </div>
          )}
          <div className="absolute bottom-1.5 inset-x-0 text-center text-[10px] font-bold text-white drop-shadow-md">You</div>
        </div>
      )}

      {/* Main Scanner Section */}
      <div className="flex flex-col items-center flex-none pt-20 px-6 pb-2 z-10 relative">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-white/5 border border-white/10 rounded-full mb-8 backdrop-blur-md">
          <Shield size={14} className={isVideo ? 'text-fuchsia-400' : 'text-blue-400'} />
          <span className="text-[11px] font-bold tracking-widest uppercase text-gray-300">
            {isVideo ? 'Enhanced Security' : 'Voice Security'}
          </span>
        </div>

        {/* Center Scanner Ring */}
        <div className="relative mb-8 flex items-center justify-center">
          {!isProcessing && (
            <>
              <div className="absolute inset-[-20px] rounded-full border-[2px] border-dashed border-indigo-500/30 animate-[spin_10s_linear_infinite]" />
              <div className="absolute inset-[-10px] rounded-full border border-pink-500/20 animate-[spin_7s_linear_infinite_reverse]" />
              <div className="absolute inset-0 rounded-full bg-indigo-500/10 animate-ping opacity-50" />
            </>
          )}
          
          <div className="w-28 h-28 rounded-full bg-gradient-to-tr from-indigo-900 via-purple-900 to-black p-1 shadow-[0_0_30px_rgba(99,102,241,0.3)]">
            <div className="w-full h-full rounded-full bg-[#050505] flex items-center justify-center border border-white/10 relative overflow-hidden">
               {isProcessing ? (
                 <Activity size={32} className="text-indigo-400 animate-pulse" />
               ) : (
                 <Fingerprint size={48} className="text-white/80 animate-pulse" strokeWidth={1} />
               )}
            </div>
          </div>
        </div>

        <h2 className="text-[22px] font-extrabold mb-1.5 tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-gray-400">Verifying Identity</h2>
        <p className="text-[13px] font-medium text-gray-400 mb-3 text-center max-w-[200px] leading-relaxed">
          {merchant ? `Securing payment to ${merchant}` : 'Analyzing transaction signals'}
        </p>

        {/* Current spoken question */}
        {currentQuestion && (
          <div className="w-full max-w-[330px] bg-white/5 border border-white/10 rounded-2xl px-4 py-3 mb-3 backdrop-blur-md">
            <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">
              {PURPOSE_LABELS[currentQuestion.purpose]}
            </p>
            <p className="text-[14px] text-white leading-snug font-medium">"{currentQuestion.text}"</p>
          </div>
        )}

        {isProcessing ? (
          <div className="flex flex-col items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: '0ms' }}/>
              <span className="w-2 h-2 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: '150ms' }}/>
              <span className="w-2 h-2 rounded-full bg-indigo-500 animate-bounce" style={{ animationDelay: '300ms' }}/>
            </div>
            <p className="text-[11px] font-bold text-indigo-400 uppercase tracking-widest">Finalizing...</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <p className="text-5xl font-light font-mono tracking-widest text-white drop-shadow-md">{timerStr}</p>
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-green-500/10 border border-green-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              <p className="text-[10px] font-bold text-green-400 uppercase tracking-wider">
                {isVideo ? 'Live Analysis' : 'Audio Analysis'}
              </p>
            </div>
          </div>
        )}

        {audioSource === 'silent' && (
          <div className="mt-4 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center gap-2 backdrop-blur-md">
            <MicOff size={14} className="text-amber-500" />
            <p className="text-[11px] font-bold uppercase tracking-wider text-amber-500">Mic unavailable — silent mode</p>
          </div>
        )}
      </div>

      {/* Question pipeline */}
      {turns.length > 0 && (
        <div className="flex-none px-5 pb-2 z-10">
          <div className="bg-white/5 border border-white/10 rounded-2xl p-2 space-y-1 backdrop-blur-md">
            {turns.map((t) => {
              const lbl = turnStatusLabel(t)
              const isActive = t.id === currentQuestion?.id
              return (
                <div
                  key={t.id}
                  className="flex items-center justify-between px-2 py-1 rounded-lg transition-colors"
                  style={{ background: isActive ? 'rgba(255,255,255,0.06)' : 'transparent' }}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="w-1.5 h-1.5 rounded-full flex-none" style={{ background: lbl.color }} />
                    <span className="text-[10px] uppercase tracking-wider text-gray-400 flex-none">
                      {PURPOSE_LABELS[t.purpose]}
                    </span>
                  </div>
                  <span className="text-[10px] font-semibold flex-none ml-2" style={{ color: lbl.color }}>
                    {lbl.text}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Analysis panels */}
      <div className="flex-1 overflow-y-auto px-5 pb-8 space-y-4 z-10 custom-scrollbar mt-2">
        {/* Hume bars */}
        <div className="bg-white/5 border border-white/10 rounded-[24px] p-5 backdrop-blur-md relative overflow-hidden">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-white/10 to-transparent" />
          <div className="flex items-center gap-2 mb-4">
            <Activity size={16} className="text-gray-400" />
            <p className="text-[11px] font-bold text-gray-300 uppercase tracking-widest">
              Biometric Telemetry
            </p>
          </div>
          
          <div className="space-y-3.5">
            {BARS.map(({ key, label, color, barGlow }) => {
              const pct = humeScores ? Math.round(humeScores[key] * 100) : 0
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-[12px] font-bold text-gray-400 w-14 flex-none uppercase tracking-wide">{label}</span>
                  <div className="flex-1 h-2 bg-black/50 rounded-full overflow-hidden border border-white/5 relative">
                    <div
                      className={`absolute top-0 left-0 h-full rounded-full transition-all duration-700 ease-out ${color} ${barGlow}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-[12px] font-mono font-bold text-gray-300 w-9 text-right flex-none">
                    {humeScores ? `${pct}%` : '–'}
                  </span>
                </div>
              )
            })}
          </div>
          
          {humeScores && (
            <div className={`mt-5 pt-3 border-t border-white/10 flex items-start gap-2
              ${humeScores.verdict_hint === 'CLEAN' ? 'text-emerald-400' :
                humeScores.verdict_hint === 'FLAGGED' ? 'text-red-400' :
                'text-amber-400'}`}>
              {humeScores.verdict_hint === 'CLEAN' ? <CheckCircle2 size={16} className="mt-0.5 flex-none" /> : 
               humeScores.verdict_hint === 'FLAGGED' ? <ShieldAlert size={16} className="mt-0.5 flex-none" /> : 
               <AlertTriangle size={16} className="mt-0.5 flex-none" />}
              <p className="text-[12px] font-semibold leading-relaxed">
                {humeScores.verdict_hint === 'CLEAN' && 'Voice telemetry is stable. No signs of stress detected.'}
                {humeScores.verdict_hint === 'AMBIGUOUS' && 'Mixed biometric signals detected. Analyzing further.'}
                {humeScores.verdict_hint === 'FLAGGED' && 'CRITICAL: High distress markers detected in voice pattern.'}
              </p>
            </div>
          )}
        </div>

        {/* Gemini */}
        {isVideo && geminiSummary && (
          <div className="bg-white/5 border border-white/10 rounded-[24px] p-5 backdrop-blur-md relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-white/10 to-transparent" />
            <div className="flex items-center gap-2 mb-3">
              <Video size={16} className="text-gray-400" />
              <p className="text-[11px] font-bold text-gray-300 uppercase tracking-widest">
                Environment Scan
              </p>
            </div>
            <p className="text-[13px] font-medium text-gray-300 leading-relaxed mb-4">{geminiSummary.raw_text}</p>
            {geminiSummary.duress_signals.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-3 border-t border-white/10">
                <span className="text-[11px] font-bold text-red-400 flex items-center gap-1 w-full mb-1">
                  <ShieldAlert size={12} /> Detected Risks
                </span>
                {geminiSummary.duress_signals.map((s) => (
                  <span key={s} className="text-[10px] font-bold uppercase tracking-wider rounded-md px-2.5 py-1 bg-red-500/10 text-red-400 border border-red-500/20">
                    {s.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}