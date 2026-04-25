import { useCallback, useRef } from 'react'

export type AudioSource = 'mic' | 'silent'

// 250ms of silence at 16kHz, 16-bit mono = 4000 samples
const SILENCE_CHUNK = (() => {
  return int16ToBase64(new Int16Array(4000))
})()

export function useAudioCapture() {
  const audioCtxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const pcmQueue = useRef<Int16Array[]>([])
  const isSilentRef = useRef(false)

  const startCapture = useCallback(async (): Promise<AudioSource> => {
    isSilentRef.current = false
    pcmQueue.current = []

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      // Request 16kHz context; browsers may honour it or resample internally
      const ctx = new AudioContext({ sampleRate: 16000 })
      audioCtxRef.current = ctx

      const actualRate = ctx.sampleRate
      const ratio = actualRate / 16000

      const source = ctx.createMediaStreamSource(stream)
      sourceNodeRef.current = source

      const analyser = ctx.createAnalyser()
      analyser.fftSize = 64
      analyser.smoothingTimeConstant = 0.8
      analyserRef.current = analyser

      // ScriptProcessorNode: 4096 samples per callback, 1 in, 1 out
      // eslint-disable-next-line @typescript-eslint/no-deprecated
      const processor = ctx.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0)
        // Downsample if browser ignored our sampleRate request
        const outLen = Math.floor(input.length / ratio)
        const int16 = new Int16Array(outLen)
        for (let i = 0; i < outLen; i++) {
          const j = Math.min(Math.floor(i * ratio), input.length - 1)
          const v = Math.max(-1, Math.min(1, input[j]))
          int16[i] = v < 0 ? Math.ceil(v * 0x8000) : Math.floor(v * 0x7fff)
        }
        pcmQueue.current.push(int16)
      }

      source.connect(analyser)
      analyser.connect(processor)
      processor.connect(ctx.destination)

      return 'mic'
    } catch {
      isSilentRef.current = true
      return 'silent'
    }
  }, [])

  const stopCapture = useCallback(() => {
    processorRef.current?.disconnect()
    analyserRef.current?.disconnect()
    sourceNodeRef.current?.disconnect()
    streamRef.current?.getTracks().forEach((t) => t.stop())
    audioCtxRef.current?.close().catch(() => {})
    processorRef.current = null
    analyserRef.current = null
    sourceNodeRef.current = null
    streamRef.current = null
    audioCtxRef.current = null
  }, [])

  // Returns a base64 PCM16 string (all data accumulated since last call).
  // Returns SILENCE_CHUNK in silent mode so the backend always gets something.
  const drainChunks = useCallback((): string => {
    if (isSilentRef.current) return SILENCE_CHUNK

    const queue = pcmQueue.current
    if (queue.length === 0) return ''
    pcmQueue.current = []

    const totalLen = queue.reduce((s, a) => s + a.length, 0)
    const combined = new Int16Array(totalLen)
    let offset = 0
    for (const arr of queue) {
      combined.set(arr, offset)
      offset += arr.length
    }
    return int16ToBase64(combined)
  }, [])

  const getFrequencies = useCallback((): Uint8Array | null => {
    if (!analyserRef.current) return null
    const data = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(data)
    return data
  }, [])

  return { startCapture, stopCapture, drainChunks, getFrequencies }
}

function int16ToBase64(int16: Int16Array): string {
  const bytes = new Uint8Array(int16.buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}
