import { useCallback, useRef } from 'react'
import { useAudioCapture, type AudioSource } from './useAudioCapture'
import type {
  GeminiSummary,
  HumeScores,
  InitiateRes,
  QuestionTurn,
  VerificationQuestion,
  VerifyResult,
} from '../types'

interface RunParams {
  initiateRes: InitiateRes
  onHumeUpdate: (scores: HumeScores) => void
  onGeminiUpdate: (summary: GeminiSummary) => void
  onCountdown: (secondsLeft: number) => void
  onVideoStream: (stream: MediaStream | null) => void
  onAudioSource: (src: AudioSource) => void
  onTurnsUpdate: (turns: QuestionTurn[]) => void
  onCurrentQuestion: (q: VerificationQuestion | null) => void
  onComplete: (result: VerifyResult) => void
  onError: (msg: string) => void
}

const ANSWER_WINDOW_MS = 5000   // listening window per question
const AUDIO_DRAIN_INTERVAL_MS = 250

function speak(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      // Fallback: resolve after a token wait so the loop still advances
      setTimeout(resolve, 800)
      return
    }
    try {
      const utter = new SpeechSynthesisUtterance(text)
      utter.rate = 0.95
      utter.pitch = 0.95
      // Pick a neutral, non-novelty voice if one is available
      const voices = window.speechSynthesis.getVoices()
      const preferred =
        voices.find((v) => /en-?US/i.test(v.lang) && /female|samantha|jenny|aria/i.test(v.name)) ||
        voices.find((v) => /en-?US/i.test(v.lang)) ||
        voices.find((v) => v.default)
      if (preferred) utter.voice = preferred
      utter.onend = () => resolve()
      utter.onerror = () => resolve()
      window.speechSynthesis.speak(utter)
    } catch {
      setTimeout(resolve, 800)
    }
  })
}

export function useVerification() {
  const { startCapture, stopCapture, drainChunks } = useAudioCapture()
  const wsRef = useRef<WebSocket | null>(null)
  const intervalsRef = useRef<number[]>([])
  const videoStreamRef = useRef<MediaStream | null>(null)
  const completedRef = useRef(false)
  const cancelledRef = useRef(false)
  // pending q_id -> resolver for the matching hume_partial
  const partialResolversRef = useRef<Map<string, (msg: any) => void>>(new Map())

  const cleanup = useCallback(() => {
    cancelledRef.current = true
    intervalsRef.current.forEach((id) => clearInterval(id))
    intervalsRef.current = []
    stopCapture()
    videoStreamRef.current?.getTracks().forEach((t) => t.stop())
    videoStreamRef.current = null
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try { window.speechSynthesis.cancel() } catch { /* noop */ }
    }
    const ws = wsRef.current
    wsRef.current = null
    if (ws && ws.readyState < WebSocket.CLOSING) {
      ws.close()
    }
    partialResolversRef.current.clear()
  }, [stopCapture])

  const run = useCallback(
    async (params: RunParams) => {
      const {
        initiateRes,
        onHumeUpdate,
        onGeminiUpdate,
        onCountdown,
        onVideoStream,
        onAudioSource,
        onTurnsUpdate,
        onCurrentQuestion,
        onComplete,
        onError,
      } = params

      completedRef.current = false
      cancelledRef.current = false
      partialResolversRef.current.clear()

      let turns: QuestionTurn[] = []

      try {
        // Capture mic
        const audioSrc = await startCapture()
        onAudioSource(audioSrc)

        // Capture video for HIGH_RISK
        let captureVideoEl: HTMLVideoElement | null = null
        let captureCanvas: HTMLCanvasElement | null = null
        if (initiateRes.tier === 'HIGH_RISK') {
          try {
            const stream = await navigator.mediaDevices.getUserMedia({
              video: { width: 320, height: 240, facingMode: 'user' },
            })
            videoStreamRef.current = stream
            onVideoStream(stream)
            captureVideoEl = document.createElement('video')
            captureVideoEl.srcObject = stream
            captureVideoEl.muted = true
            captureVideoEl.playsInline = true
            captureVideoEl.autoplay = true
            await captureVideoEl.play()
            captureCanvas = document.createElement('canvas')
            captureCanvas.width = 320
            captureCanvas.height = 240
          } catch {
            onVideoStream(null)
          }
        }

        // Open WS
        const apiBase =
          (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'
        const wsBase = apiBase.replace(/^http/, 'ws')
        const ws = new WebSocket(`${wsBase}${initiateRes.ws_url}`)
        wsRef.current = ws

        let questions: VerificationQuestion[] = []
        let resolveReady: () => void = () => {}
        const readyPromise = new Promise<void>((r) => { resolveReady = r })

        ws.onmessage = (event) => {
          if (cancelledRef.current) return
          let msg: any
          try { msg = JSON.parse(event.data as string) } catch { return }

          if (msg.type === 'ready') {
            questions = (msg.questions ?? []) as VerificationQuestion[]
            turns = questions.map((q) => ({
              id: q.id,
              text: q.text,
              purpose: q.purpose,
              status: 'pending' as const,
            }))
            onTurnsUpdate(turns)
            resolveReady()
            return
          }

          if (msg.type === 'hume_partial') {
            const scores = msg.scores as HumeScores
            const qId = msg.q_id as string | undefined
            const delta = msg.delta_vs_baseline as QuestionTurn['delta_vs_baseline'] | undefined
            onHumeUpdate(scores)
            if (qId) {
              const resolve = partialResolversRef.current.get(qId)
              if (resolve) {
                resolve({ scores, delta })
                partialResolversRef.current.delete(qId)
              }
            }
            return
          }

          if (msg.type === 'gemini_partial') {
            onGeminiUpdate(msg.summary as GeminiSummary)
            return
          }

          if (msg.type === 'decision') {
            completedRef.current = true
            onComplete({
              verdict: msg.verdict,
              rationale: msg.rationale,
            })
            cleanup()
            return
          }

          if (msg.type === 'error') {
            completedRef.current = true
            onError(msg.reason as string)
            cleanup()
            return
          }
        }

        ws.onerror = () => {
          if (!completedRef.current) {
            completedRef.current = true
            onError('WebSocket connection error')
            cleanup()
          }
        }

        ws.onclose = (event) => {
          if (!event.wasClean && !completedRef.current) {
            completedRef.current = true
            onError('Connection closed unexpectedly')
            cleanup()
          }
        }

        // Wait for socket open + ready event with questions
        await new Promise<void>((res, rej) => {
          ws.onopen = () => {
            ws.send(JSON.stringify({ type: 'start' }))
            res()
          }
          // bail after 15s if no open
          setTimeout(() => rej(new Error('ws_open_timeout')), 15000)
        })
        await readyPromise

        if (cancelledRef.current) return

        // Start a low-rate video capture stream (HIGH_RISK only, max 8 frames)
        if (captureVideoEl && captureCanvas) {
          const ctx2d = captureCanvas.getContext('2d')!
          let frameCount = 0
          const videoId = window.setInterval(() => {
            if (frameCount >= 8) return
            try {
              ctx2d.drawImage(captureVideoEl!, 0, 0, 320, 240)
              const data = captureCanvas!.toDataURL('image/jpeg', 0.7).split(',')[1]
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'video_frame', data }))
                frameCount++
              }
            } catch { /* canvas not ready */ }
          }, 700)
          intervalsRef.current.push(videoId)
        }

        // Per-question loop — sequential
        for (let i = 0; i < questions.length; i++) {
          if (cancelledRef.current) return
          const q = questions[i]

          // UI: this question is now active
          onCurrentQuestion(q)
          turns = turns.map((t) => t.id === q.id ? { ...t, status: 'speaking' } : t)
          onTurnsUpdate(turns)

          // Speak the question via browser TTS
          await speak(q.text)
          if (cancelledRef.current) return

          // Drain any audio captured during the speak() (user may have spoken
          // over the question — discard it so we baseline cleanly).
          drainChunks()

          // Listening window
          turns = turns.map((t) => t.id === q.id ? { ...t, status: 'listening' } : t)
          onTurnsUpdate(turns)

          const startedAt = Date.now()
          onCountdown(Math.ceil(ANSWER_WINDOW_MS / 1000))

          await new Promise<void>((res) => {
            const drainId = window.setInterval(() => {
              const chunk = drainChunks()
              if (chunk && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'audio_chunk', q_id: q.id, data: chunk }))
              }
              const remaining = ANSWER_WINDOW_MS - (Date.now() - startedAt)
              onCountdown(Math.max(0, Math.ceil(remaining / 1000)))
              if (remaining <= 0) {
                clearInterval(drainId)
                intervalsRef.current = intervalsRef.current.filter((id) => id !== drainId)
                res()
              }
            }, AUDIO_DRAIN_INTERVAL_MS)
            intervalsRef.current.push(drainId)
          })
          if (cancelledRef.current) return

          // Send any final residue chunk
          const tail = drainChunks()
          if (tail && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'audio_chunk', q_id: q.id, data: tail }))
          }

          // Signal end of answer + attach the per-Q scoring resolver
          turns = turns.map((t) => t.id === q.id ? { ...t, status: 'scoring' } : t)
          onTurnsUpdate(turns)

          const scoredPromise = new Promise<{ scores: HumeScores; delta?: QuestionTurn['delta_vs_baseline'] }>(
            (resolve) => { partialResolversRef.current.set(q.id, resolve) },
          )
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'answer_end', q_id: q.id, transcript: '' }))
          }

          // Wait for the matching hume_partial — bound the wait to keep the
          // demo moving even if the provider hangs.
          const scored = await Promise.race([
            scoredPromise,
            new Promise<{ scores: HumeScores; delta?: QuestionTurn['delta_vs_baseline'] }>((res) =>
              setTimeout(() => res({
                scores: {
                  calmness: 0, fear: 0, distress: 0, anxiety: 0,
                  confidence_overall: 0, verdict_hint: 'AMBIGUOUS',
                  service_available: false, note: 'timeout',
                },
                delta: undefined,
              }), 20000),
            ),
          ])

          if (cancelledRef.current) return

          turns = turns.map((t) =>
            t.id === q.id
              ? { ...t, status: 'done' as const, scores: scored.scores, delta_vs_baseline: scored.delta }
              : t,
          )
          onTurnsUpdate(turns)
        }

        // All questions answered — close out the verification
        onCurrentQuestion(null)
        intervalsRef.current.forEach((id) => clearInterval(id))
        intervalsRef.current = []
        stopCapture()
        if (captureVideoEl) {
          captureVideoEl.pause()
          captureVideoEl.srcObject = null
        }

        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'end' }))
        }
        // Decision arrives via onmessage handler.
      } catch (e) {
        if (!cancelledRef.current) {
          onError(`Setup failed: ${String(e)}`)
        }
        cleanup()
      }
    },
    [startCapture, stopCapture, drainChunks, cleanup],
  )

  return { run, cleanup }
}
